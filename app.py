#!/usr/bin/env python3
import os
import json
from pathlib import Path
from flask import Flask, render_template, request, redirect, url_for, jsonify, send_file, flash
from werkzeug.utils import secure_filename
from samsungtvws import SamsungTVWS
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = 'your-secret-key-change-this'
app.config['MAX_CONTENT_LENGTH'] = 32 * 1024 * 1024  # 32MB max file size

# Configuration
IMAGES_DIR = Path('./images')
CONFIG_FILE = Path('./config.json')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}

# Ensure images directory exists
IMAGES_DIR.mkdir(exist_ok=True)

def load_config():
    """Load configuration from file"""
    default_config = {'tv_ip': '192.168.1.22', 'tv_token': None}
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading config: {e}")
    return default_config

def save_config(config):
    """Save configuration to file"""
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=2)
        return True
    except Exception as e:
        logger.error(f"Error saving config: {e}")
        return False

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def is_tv_paired():
    """Check if TV is already paired (has token)"""
    config = load_config()
    return config.get('tv_token') is not None

def get_tv_connection():
    """Get Samsung TV connection with token"""
    config = load_config()
    try:
        if config.get('tv_token'):
            return SamsungTVWS(
                host=config['tv_ip'],
                port=8002,
                token=config['tv_token']
            )
        else:
            return SamsungTVWS(
                host=config['tv_ip'],
                port=8002
            )
    except Exception as e:
        logger.error(f"Error connecting to TV: {e}")
        return None

@app.route('/')
def index():
    """Main page with image gallery and upload form"""
    config = load_config()
    paired = is_tv_paired()

    # Get local images
    images = []
    for img_file in IMAGES_DIR.glob('*'):
        if img_file.is_file() and allowed_file(img_file.name):
            images.append({
                'filename': img_file.name,
                'size': img_file.stat().st_size
            })

    images.sort(key=lambda x: x['filename'])

    return render_template('index.html',
                         images=images,
                         tv_ip=config['tv_ip'],
                         tv_paired=paired)

@app.route('/upload', methods=['POST'])
def upload_files():
    """Handle file upload"""
    if 'files[]' not in request.files:
        flash('No files selected')
        return redirect(url_for('index'))

    files = request.files.getlist('files[]')
    uploaded_count = 0

    for file in files:
        if file and file.filename and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            filepath = IMAGES_DIR / filename
            file.save(filepath)
            uploaded_count += 1
            logger.info(f"Uploaded: {filename}")

    flash(f'Successfully uploaded {uploaded_count} files')
    return redirect(url_for('index'))

@app.route('/image/<filename>')
def serve_image(filename):
    """Serve local images"""
    return send_file(IMAGES_DIR / filename)

@app.route('/send-to-tv/<filename>')
def send_to_tv(filename):
    """Send image to Samsung TV"""
    if not is_tv_paired():
        flash('❌ TV not paired. Please pair your TV first.')
        return redirect(url_for('index'))

    config = load_config()
    image_path = IMAGES_DIR / filename

    if not image_path.exists():
        flash(f'Image not found: {filename}')
        return redirect(url_for('index'))

    try:
        logger.info(f"Sending {filename} to TV at {config['tv_ip']}")

        with open(image_path, 'rb') as f:
            image_data = f.read()

        file_ext = filename.rsplit('.', 1)[1].lower()
        file_type = 'png' if file_ext == 'png' else 'jpg'

        logger.info(f"Image size: {len(image_data)} bytes, type: {file_type}")

        # Create TV connection with token
        tv = SamsungTVWS(
            host=config['tv_ip'],
            port=8002,
            token=config['tv_token']
        )

        # Upload to TV
        art_api = tv.art()
        result = art_api.upload(image_data, file_type=file_type)

        flash(f'✅ Successfully sent {filename} to Samsung Frame TV')
        logger.info(f"Successfully sent {filename} to TV")

    except Exception as e:
        logger.error(f"Error sending {filename} to TV: {e}")
        flash(f'❌ Failed to send {filename}: {str(e)}')

    return redirect(url_for('index'))

@app.route('/config', methods=['POST'])
def update_config():
    """Update TV IP configuration"""
    tv_ip = request.form.get('tv_ip', '').strip()
    if tv_ip:
        config = load_config()
        config['tv_ip'] = tv_ip
        if save_config(config):
            flash(f'TV IP updated to {tv_ip}')
        else:
            flash('Error saving configuration')
    else:
        flash('Please enter a valid IP address')

    return redirect(url_for('index'))

@app.route('/pair-tv')
def pair_tv():
    """Pair with Samsung TV"""
    config = load_config()

    try:
        logger.info(f"Pairing with TV at {config['tv_ip']}")

        # Create connection that will trigger pairing popup on TV
        tv = SamsungTVWS(
            host=config['tv_ip'],
            port=8002,
            name="The Frame Art Manager"
        )

        # Force a connection that requires authentication
        device_info = tv.rest_device_info()
        logger.info(f"Connected to: {device_info.get('name', 'Samsung TV')}")

        # Try to access art API to trigger token creation
        art = tv.art()
        available = art.available()

        # Get the token from the connection
        token = getattr(tv, 'token', None)
        if token:
            config['tv_token'] = token
            save_config(config)
            logger.info(f"Token saved: {token}")

            return jsonify({
                'success': True,
                'message': f'Successfully paired with {device_info.get("name", "Samsung TV")}',
                'art_count': len(available)
            })
        else:
            return jsonify({
                'error': 'Pairing failed - no token received. Make sure you accepted the popup on your TV screen.'
            })

    except Exception as e:
        logger.error(f"Pairing error: {e}")
        return jsonify({
            'error': str(e),
            'instructions': [
                '1. Make sure your Samsung TV is ON and in Art Mode',
                '2. Watch your TV screen for a popup asking to allow connection',
                '3. Use your TV remote to select "Allow" or "Yes"',
                '4. If no popup appears, try turning TV off and on again'
            ]
        })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5600, debug=True)
