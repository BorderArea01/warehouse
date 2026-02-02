import requests
from PIL import Image, ImageDraw
import io
import os


def test_upload_local_images():
    image_dir = "/home/lzwc/project/ai_warehouse/images"
    url = "http://192.168.11.24:8088/system/visitorRecord/recognizeFace"
    
    if not os.path.exists(image_dir):
        print(f"Directory {image_dir} does not exist.")
        return

    for filename in os.listdir(image_dir):
        if filename.lower().endswith(('.png', '.jpg', '.jpeg')):
            file_path = os.path.join(image_dir, filename)
            print(f"\nProcessing file: {filename}")
            
            try:
                with open(file_path, 'rb') as f:
                    img_data = f.read()
                
                # Use only the basename for the filename argument to avoid path issues on server
                # Previous error: "Unable to create temporary file, ...images/20260202-195147.jpg"
                # suggests that passing a path instead of a filename might cause server-side path concatenation errors.
                files = {
                    'file': (filename, img_data, 'image/jpeg')
                }
                
                print(f"Sending POST request to {url}...")
                response = requests.post(url, files=files, timeout=30)
                
                print(f"Status Code: {response.status_code}")
                try:
                    print(f"Response Body: {response.json()}")
                except:
                    print(f"Response Body: {response.text}")
                    
            except Exception as e:
                print(f"Error processing {filename}: {e}")

if __name__ == "__main__":
    # test_upload() # Original dummy test
    test_upload_local_images()
