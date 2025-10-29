# Samsung Frame TV Art Manager

A simple Python web application to manage artwork for Samsung Frame TVs.

## Features

- Upload multiple images to a local directory
- View image gallery with thumbnails 
- Send images directly to Samsung Frame TV
- Configure TV IP address (persistent config)
- Simple, no-frills web interface

## Requirements

- Python 3.11+
- Samsung Frame TV on the same network
- TV must be turned on and Art Mode enabled

## Installation

1. Clone or download this project
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Run the application:
   ```bash
   python app.py
   ```

4. Open your browser to `http://localhost:5000`

## Docker Usage

Build and run with Docker:

```bash
docker build -t frame-art .
docker run -p 5000:5000 -v $(pwd)/images:/app/images -v $(pwd)/config.json:/app/config.json frame-art
```

## Usage

1. Set your Samsung TV's IP address in the configuration section
2. Upload images using the upload form (supports PNG, JPG, JPEG)
3. View uploaded images in the gallery
4. Click "Send to TV" to upload an image to your Samsung Frame TV
5. Use "Check TV Status" to see current TV art information

## Configuration

The TV IP address is stored in `config.json` and persists between restarts.

## File Structure

- `app.py` - Main Flask application
- `templates/index.html` - Web interface
- `images/` - Directory for uploaded images
- `config.json` - Configuration file (auto-created)
- `requirements.txt` - Python dependencies
- `Dockerfile` - Docker container configuration