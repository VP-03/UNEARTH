import os
import pytsk3
import datetime
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext
from PIL import Image, ImageTk
import fitz
import tempfile
from docx import Document
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaInMemoryUpload

SCOPES = ['https://www.googleapis.com/auth/drive.file']

USER_FILE_EXTENSIONS = ['.txt', '.doc', '.docx', '.pdf', '.jpg', '.jpeg', '.png', '.mp3', '.mp4', 
                        '.xls', '.xlsx', '.ppt', '.pptx', '.csv', '.zip', '.rar', '.7z', 
                        '.rtf', '.odt', '.ods', '.odp', '.gif', '.bmp', '.tiff', '.wav', '.avi',
                        '.mov', '.wmv', '.html', '.htm', '.xml', '.json', '.log', '.cfg']

class DeletedFile:
    def __init__(self, name, path, size, delete_time, content):
        self.name = name
        self.path = path
        self.size = size
        self.delete_time = delete_time
        self.content = content

def find_deleted_user_files(image_path):
    deleted_files = []
    total_files_checked = 0
    deleted_files_found = 0

    try:
        img_handle = pytsk3.Img_Info(image_path)
        fs_handle = pytsk3.FS_Info(img_handle)
    except IOError as e:
        messagebox.showerror("Error", f"Error opening image or filesystem: {e}")
        return []

    def process_directory(directory, path=""):
        nonlocal total_files_checked, deleted_files_found
        try:
            for entry in directory:
                if entry.info.name.name in [b".", b".."]:
                    continue
                
                try:
                    file_type = entry.info.name.type
                    file_name = entry.info.name.name.decode('utf-8')
                    total_files_checked += 1
                    
                    if file_type == pytsk3.TSK_FS_NAME_TYPE_REG:
                        full_path = f"{path}/{file_name}"
                        file_size = entry.info.meta.size
                        is_deleted = entry.info.meta.flags & pytsk3.TSK_FS_META_FLAG_UNALLOC
                        is_user_file = any(file_name.lower().endswith(ext) for ext in USER_FILE_EXTENSIONS)
                        
                        # Check for recent modification or creation
                        mtime = datetime.datetime.fromtimestamp(entry.info.meta.mtime)
                        ctime = datetime.datetime.fromtimestamp(entry.info.meta.crtime)
                        is_recent = (datetime.datetime.now() - mtime).days < 7 or (datetime.datetime.now() - ctime).days < 7

                        print(f"Checking file: {file_name}")
                        print(f"  Path: {full_path}")
                        print(f"  Size: {file_size} bytes")
                        print(f"  Is Deleted: {is_deleted}")
                        print(f"  Is User File: {is_user_file}")
                        print(f"  Is Recent: {is_recent}")

                        if (is_deleted or is_recent) and is_user_file:
                            deleted_files_found += 1
                            delete_time = mtime if is_deleted else ctime

                            try:
                                # Read file content
                                offset = 0
                                size = min(1024*1024, file_size)  # Read up to 1KB for preview
                                content = entry.read_random(offset, size)
                                
                                deleted_file = DeletedFile(file_name, full_path, file_size, 
                                                           delete_time.strftime('%Y-%m-%d %H:%M:%S'),
                                                           content)
                                deleted_files.append(deleted_file)
                                
                                print(f"Added to recovery list: {file_name}")
                            except IOError as e:
                                print(f"Error reading file {file_name}: {str(e)}")
                    
                    if file_type == pytsk3.TSK_FS_NAME_TYPE_DIR:
                        new_path = f"{path}/{file_name}"
                        sub_directory = entry.as_directory()
                        process_directory(sub_directory, new_path)
                        
                except Exception as e:
                    print(f"Error processing {file_name}: {str(e)}")

        except Exception as e:
            print(f"Error accessing directory {path}: {str(e)}")

    root_dir = fs_handle.open_dir(path="/")
    process_directory(root_dir)
    
    print(f"Total files checked: {total_files_checked}")
    print(f"Deleted or user files found: {deleted_files_found}")
    print(f"Files added to recovery list: {len(deleted_files)}")
    
    return deleted_files

class DataRetrievalApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Data Recovery Tool")
        
        # UI elements
        tk.Button(self.root, text="Select Image File", command=self.select_image).pack(pady=10)
        tk.Button(self.root, text="Find Deleted User Files", command=self.find_files).pack(pady=10)

        self.file_listbox = tk.Listbox(self.root, width=70)
        self.file_listbox.pack(pady=10)
        self.file_listbox.bind('<<ListboxSelect>>', self.on_select)
        
        self.btn_preview = tk.Button(self.root, text="Preview Selected File", command=self.preview_file)
        self.btn_preview.pack(pady=10)
        
        self.btn_save = tk.Button(self.root, text="Save Selected File As...", command=self.save_file_as)
        self.btn_save.pack(pady=10)

        self.btn_backup = tk.Button(self.root, text="Backup Selected File to Google Drive", command=self.backup_to_google_drive)
        self.btn_backup.pack(pady=10)
        
        self.recovered_files = []
        self.google_drive_service = None
        
        self.SCOPES = ['https://www.googleapis.com/auth/drive.file']
        self.credentials = None
        self.service = None
        self.load_google_credentials()

    def select_image(self):
        self.image_path = filedialog.askopenfilename(filetypes=[("Image files", "*.img *.dd")])
        if self.image_path:
            messagebox.showinfo("Image Selected", f"Selected image: {self.image_path}")

    def find_files(self):
        if not self.image_path:
            messagebox.showerror("Error", "Please select an image file first.")
            return

        self.deleted_files = find_deleted_user_files(self.image_path)
        self.update_file_list()

    def update_file_list(self):
        self.file_listbox.delete(0, tk.END)
        for file in self.deleted_files:
            self.file_listbox.insert(tk.END, f"{file.name} ({file.size} bytes)")

    def on_select(self, event):
        selection = self.file_listbox.curselection()
        if selection:
            self.current_selection = self.deleted_files[selection[0]]

    def load_google_credentials(self):
        creds = None
        # The file token.json stores the user's access and refresh tokens, and is
        # created automatically when the authorization flow completes for the first time.
        if os.path.exists('token.json'):
            os.remove('token.json')
        # If there are no (valid) credentials available, let the user log in.
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    'credentials.json', self.SCOPES)
                creds = flow.run_local_server(port=0)
            # Save the credentials for the next run
            with open('token.json', 'w') as token:
                token.write(creds.to_json())
        self.credentials = creds
        self.service = build('drive', 'v3', credentials=creds)
    
    def backup_to_google_drive(self):
        selected_file = self.get_selected_file()
        if selected_file:
            file_name = selected_file.name
            file_metadata = {'name': file_name}
            mime_type = self.get_mime_type(file_name)
        
            try:
                # Create media object directly from the file content
                media = MediaInMemoryUpload(selected_file.content, mimetype=mime_type, resumable=True)
            
                # Execute the file upload
                file = self.service.files().create(body=file_metadata,
                                               media_body=media,
                                               fields='id').execute()
            
                messagebox.showinfo("Backup Successful", f"File backed up to Google Drive with ID: {file.get('id')}")
            except Exception as e:
                messagebox.showerror("Error", f"Could not backup the file to Google Drive: {str(e)}")
                print(f"Detailed error: {e}")  # This will print the full error message to the console
        else:
            messagebox.showerror("Error", "Please select a file to backup.")

    def get_mime_type(self, file_path):
        _, file_extension = os.path.splitext(file_path)
        if file_extension.lower() == '.pdf':
            return 'application/pdf'
        elif file_extension.lower() in ('.jpg', '.jpeg'):
            return 'image/jpeg'
        elif file_extension.lower() == '.png':
            return 'image/png'
        elif file_extension.lower() == '.txt':
            return 'text/plain'
        else:
            return 'application/octet-stream'
        
    def browse_path(self):
        path = filedialog.askdirectory()
        self.entry_path.delete(0, tk.END)
        self.entry_path.insert(0, path)
        
    def recover_files(self):
        target_path = self.entry_path.get()
        if not target_path:
            messagebox.showerror("Error", "Please select a valid path.")
            return
        
        self.file_listbox.delete(0, tk.END)
        
        recovered_files = find_deleted_user_files(target_path)
        
        if recovered_files:
            self.recovered_files = recovered_files
            for file_path in self.recovered_files:
                file_name = os.path.basename(file_path)
                self.file_listbox.insert(tk.END, f"{file_name}\n")
            messagebox.showinfo("Recovery Complete", "File recovery completed successfully.")
        else:
            self.file_listbox.insert(tk.END, "No files recovered.\n")
            messagebox.showinfo("No Files Recovered", "No recoverable files found.")
    
    def preview_file(self):
        if hasattr(self, 'current_selection'):
            file = self.current_selection
            try:
                # Preview based on file extension
                _, file_extension = os.path.splitext(file.name)
                file_extension = file_extension.lower()
            
                if file_extension in ('.jpg', '.jpeg', '.png', '.gif', '.bmp'):
                    self.preview_image(file)
                elif file_extension == '.pdf':
                    self.preview_pdf(file)
                elif file_extension == '.docx':
                    self.preview_docx(file)
                else:
                    self.preview_text(file)
            except Exception as e:
                messagebox.showerror("Error", f"Could not preview the file: {e}")
        else:
            messagebox.showerror("Error", "Please select a file to preview.")
    
    def preview_image(self, image_path):
        try:
        # Create a temporary file to save the image content
            with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(image_path.name)[1]) as temp_file:
                temp_file.write(image_path.content)
                temp_file_path = temp_file.name

            image = Image.open(temp_file_path)
            image = image.resize((600, 400))
            photo = ImageTk.PhotoImage(image)
        
            preview_window = tk.Toplevel(self.root)
            preview_window.title(f"Preview: {image_path.name}")
            label = tk.Label(preview_window, image=photo)
            label.pack(padx=10, pady=10)
        
            label.image = photo  # keep a reference to prevent garbage collection

            # Schedule deletion of temporary file
            preview_window.after(100, lambda: os.unlink(temp_file_path))
        except Exception as e:
            messagebox.showerror("Error", f"Could not preview the image: {e}")
        
    def preview_pdf(self, pdf_path):
        try:
            # Create a temporary file to save the PDF content
            with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as temp_file:
                temp_file.write(pdf_path.content)
                temp_file_path = temp_file.name

            doc = fitz.open(temp_file_path)
            num_pages = doc.page_count
        
            preview_window = tk.Toplevel(self.root)
            preview_window.title(f"Preview: {pdf_path.name}")
            pdf_text = scrolledtext.ScrolledText(preview_window, width=80, height=20)
            pdf_text.pack(padx=10, pady=10)
        
            for page_num in range(num_pages):
                page = doc.load_page(page_num)
                pdf_text.insert(tk.END, page.get_text())
                pdf_text.insert(tk.END, "\n\n")
            
            pdf_text.config(state=tk.DISABLED)

            # Close the document and schedule deletion of temporary file
            doc.close()
            preview_window.after(100, lambda: os.unlink(temp_file_path))
        except Exception as e:
            messagebox.showerror("Error", f"Could not preview the PDF: {e}")
    
    def preview_docx(self, docx_path):
        try:
        # Create a temporary file to save the DOCX content
            with tempfile.NamedTemporaryFile(delete=False, suffix='.docx') as temp_file:
                temp_file.write(docx_path.content)
                temp_file_path = temp_file.name

            doc = Document(temp_file_path)
            content = []
            for paragraph in doc.paragraphs:
                content.append(paragraph.text)
            
            preview_window = tk.Toplevel(self.root)
            preview_window.title(f"Preview: {docx_path.name}")
            docx_text = scrolledtext.ScrolledText(preview_window, width=80, height=20)
            docx_text.pack(padx=10, pady=10)
        
            for line in content:
                docx_text.insert(tk.END, line + "\n")
            
            docx_text.config(state=tk.DISABLED)

            # Schedule deletion of temporary file
            preview_window.after(100, lambda: os.unlink(temp_file_path))
        except Exception as e:
            messagebox.showerror("Error", f"Could not preview the file: {e}")

    def preview_text(self, text_path):
        try:
            preview_window = tk.Toplevel(self.root)
            preview_window.title(f"Preview: {text_path.name}")
            preview_text = scrolledtext.ScrolledText(preview_window, width=80, height=20)
            preview_text.pack(padx=10, pady=10)
            preview_text.insert(tk.END, text_path.content.decode('utf-8', errors='replace'))
            preview_text.config(state=tk.DISABLED)
        except Exception as e:
            messagebox.showerror("Error", f"Could not preview the file: {e}")
        
    def save_file_as(self):
        selected_file = self.get_selected_file()
        if selected_file:
            save_path = filedialog.asksaveasfilename(initialfile=selected_file.name)
            if save_path:
                try:
                    with open(save_path, 'wb') as file:
                        file.write(selected_file.content)
                    messagebox.showinfo("Save Successful", f"File saved as {save_path}")
                except Exception as e:
                    messagebox.showerror("Error", f"Could not save the file: {e}")
        else:
            messagebox.showerror("Error", "Please select a file to save.")
    
    def get_selected_file(self):
        if hasattr(self, 'current_selection'):
            return self.current_selection
        return None

def main():
    root = tk.Tk()
    app = DataRetrievalApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()