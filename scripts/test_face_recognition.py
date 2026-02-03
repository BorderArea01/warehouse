import requests
from PIL import Image, ImageDraw
import io
import os


def recognize_face(img_data, filename, url="http://192.168.11.24:8088/system/visitorRecord/recognizeFace"):
    """
    Sends image data to the face recognition API.
    
    Args:
        img_data (bytes): The binary image data.
        filename (str): The filename to send with the image.
        url (str): The API URL.
        
    Returns:
        dict or str: The JSON response or text response, or None on error.
    """
    try:
        # Use only the basename for the filename argument to avoid path issues on server
        files = {
            'file': (filename, img_data, 'image/jpeg')
        }
        
        print(f"Sending POST request to {url}...")
        response = requests.post(url, files=files, timeout=30)
        
        print(f"Status Code: {response.status_code}")
        try:
            result = response.json()
            print(f"Response Body: {result}")
            return result
        except:
            print(f"Response Body: {response.text}")
            return response.text
            
    except Exception as e:
        print(f"Error processing {filename}: {e}")
        return None

def test_upload_local_images():
    image_dir = "./images"
    
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
                
                recognize_face(img_data, filename)
                    
            except Exception as e:
                print(f"Error reading {filename}: {e}")

if __name__ == "__main__":
    # test_upload() # Original dummy test
    test_upload_local_images()
