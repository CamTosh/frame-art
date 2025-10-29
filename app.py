#!/usr/bin/env python3
import time
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
    default_config = {'tv_ip': '192.168.1.22', 'tv_token': None}
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading config: {e}")
    return default_config

def save_config(config):
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
    config = load_config()
    return config.get('tv_token') is not None

def get_tv_connection():
    config = load_config()
    try:
        if config.get('tv_token'):
            return SamsungTVWS(
                host=config['tv_ip'],
                port=8002,
                token=config['tv_token'],
                name='Frame Art Manager'
            )
        else:
            return SamsungTVWS(
                host=config['tv_ip'],
                port=8002,
                name='Frame Art Manager'
            )
    except Exception as e:
        logger.error(f"Error connecting to TV: {e}")
        return None

@app.route('/')
def index():
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
    return send_file(IMAGES_DIR / filename)

@app.route('/send-to-tv/<filename>')
def send_to_tv(filename):
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

        # Check image size - Samsung TVs have limits
        max_size = 20 * 1024 * 1024  # 20MB limit
        if len(image_data) > max_size:
            flash(f'❌ Image too large: {len(image_data)/1024/1024:.1f}MB (max 20MB)')
            return redirect(url_for('index'))

        tv = get_tv_connection()

        file_type_upper = file_type.upper()  # Samsung expects uppercase
        result = tv.art().upload(image_data, file_type=file_type_upper, matte="none")
        logger.info(f"Upload result: {result}")

        flash(f'✅ Successfully sent {filename} to Samsung Frame TV')
        logger.info(f"Successfully sent {filename} to TV")

    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error sending {filename} to TV: {e}")

        if "Broken pipe" in error_msg:
            flash(f'❌ Upload failed: Connection lost during transfer. Try a smaller image or check TV network.')
        elif "Connection refused" in error_msg:
            flash(f'❌ Upload failed: TV refused connection. Try pairing again.')
        elif "timeout" in error_msg.lower():
            flash(f'❌ Upload failed: Connection timeout. Check network.')
        else:
            flash(f'❌ Failed to send {filename}: {error_msg}')

    return redirect(url_for('index'))

@app.route('/config', methods=['POST'])
def update_config():
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
    config = load_config()

    try:
        logger.info(f"Pairing with TV at {config['tv_ip']}")
        tv = get_tv_connection()

        device_info = tv.rest_device_info()
        logger.info(f"Connected to: {device_info.get('name', 'Samsung TV')}")

        # Try multiple approaches to trigger popup
        logger.info("Method 1: Opening WebSocket connection...")
        tv.open()
        time.sleep(3)

        # Try sending a remote key to trigger authentication
        try:
            logger.info("Method 2: Sending test remote key...")
            tv.send_key('KEY_POWER')  # This should definitely trigger auth
            time.sleep(1)
        except Exception as key_e:
            logger.info(f"Remote key failed (expected): {key_e}")

        # Try to access art API
        logger.info("Method 3: Accessing art API...")
        art = tv.art()
        available = art.available()

        tv.close()

        # Check for token
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
                'error': 'No popup appeared or was dismissed. Try these steps:',
                'instructions': [
                    '1. POWER OFF your Samsung TV completely (unplug for 30 seconds)',
                    '2. Power it back ON and wait for full boot',
                    '3. Put TV in Art Mode (press Art button on remote)',
                    '4. Make sure no other apps are connected to the TV',
                    '5. Try pairing again - popup should appear immediately'
                ]
            })

    except Exception as e:
        logger.error(f"Pairing error: {e}")
        return jsonify({
            'error': str(e),
            'instructions': [
                '1. TV might have cached old connection data',
                '2. Go to TV Settings → General → External Device Manager → Device Connect Manager',
                '3. Look for any "Frame Art Manager" entries and DELETE them',
                '4. Restart TV completely (unplug/plug)',
                '5. Try pairing again'
            ]
        })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5600, debug=True)
