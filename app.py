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
TOKEN_FILE = Path('./tv-token.txt')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}

# Ensure images directory exists
IMAGES_DIR.mkdir(exist_ok=True)

def load_config():
    """Load configuration from file"""
    default_config = {'tv_ip': '192.168.1.106', 'tv_token': None}
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, 'r') as f:
                config = json.load(f)
                # Migrate token from file if it exists
                if TOKEN_FILE.exists() and not config.get('tv_token'):
                    with open(TOKEN_FILE, 'r') as tf:
                        config['tv_token'] = tf.read().strip()
                    save_config(config)
                    logger.info(f"Migrated token to config: {config['tv_token']}")
                return config
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

def get_tv_connection():
    """Get Samsung TV connection with token authentication"""
    config = load_config()
    try:
        # Use token from config if available
        if config.get('tv_token'):
            tv = SamsungTVWS(
                host=config['tv_ip'],
                port=8002,
                token=config['tv_token']
            )
        else:
            tv = SamsungTVWS(
                host=config['tv_ip'],
                port=8002,
                token_file=str(TOKEN_FILE)
            )
        return tv
    except Exception as e:
        logger.error(f"Error connecting to TV at {config['tv_ip']}: {e}")
        return None

@app.route('/')
def index():
    """Main page with image gallery and upload form"""
    config = load_config()

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
                         tv_ip=config['tv_ip'])

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
    config = load_config()
    
    image_path = IMAGES_DIR / filename
    if not image_path.exists():
        flash(f'Image not found: {filename}')
        return redirect(url_for('index'))

    try:
        logger.info(f"Attempting to send {filename} to TV at {config['tv_ip']}")
        
        with open(image_path, 'rb') as f:
            image_data = f.read()

        # Determine file type
        file_ext = filename.rsplit('.', 1)[1].lower()
        file_type = 'png' if file_ext == 'png' else 'jpg'
        
        logger.info(f"Image size: {len(image_data)} bytes, type: {file_type}")

        # Use the get_tv_connection function which handles token properly
        tv = get_tv_connection()
        if not tv:
            flash('Cannot connect to TV. Check configuration.')
            return redirect(url_for('index'))

        # Get art API and upload
        art_api = tv.art()
        logger.info("Art API connection established")
        
        # Upload to TV with proper error handling
        result = art_api.upload(image_data, file_type=file_type)
        logger.info(f"Upload result: {result}")
        
        flash(f'✅ Successfully sent {filename} to TV')
        logger.info(f"Successfully sent {filename} to TV")

    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error sending {filename} to TV: {e}")
        
        # Try alternative approach - direct connection with token
        try:
            logger.info("Trying direct token connection...")
            if config.get('tv_token'):
                tv_direct = SamsungTVWS(
                    host=config['tv_ip'],
                    port=8002,
                    token=config['tv_token']
                )
                art_api = tv_direct.art()
                result = art_api.upload(image_data, file_type=file_type)
                flash(f'✅ Successfully sent {filename} to TV (direct token)')
                logger.info(f"Successfully sent {filename} to TV with direct token")
            else:
                raise Exception("No token available")
                
        except Exception as e2:
            logger.error(f"All upload methods failed: {e2}")
            
            # Specific error messages
            if "Connection refused" in str(e2):
                flash('❌ Connection refused - TV may not be in Art Mode or network issue')
            elif "timeout" in str(e2).lower():
                flash('❌ Connection timeout - check TV IP and network')
            elif "Unauthorized" in str(e2):
                flash('❌ Unauthorized - try Force Pair TV again')
            else:
                flash(f'❌ Upload failed: {str(e2)}')

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

@app.route('/tv-art')
def tv_art():
    """Get current TV art info"""
    tv = get_tv_connection()
    if not tv:
        return jsonify({'error': 'Cannot connect to TV'})

    try:
        art = tv.art()
        available = art.available()
        current = art.get_current()

        return jsonify({
            'available_count': len(available),
            'current': current
        })
    except Exception as e:
        return jsonify({'error': str(e)})

@app.route('/pair-tv')
def pair_tv():
    """Test TV connection and initiate pairing if needed"""
    config = load_config()
    try:
        # Create connection with token file to trigger pairing process
        tv = SamsungTVWS(
            host=config['tv_ip'], 
            port=8002, 
            token_file=str(TOKEN_FILE)
        )
        
        # Test basic connection by getting device info
        info = tv.rest_device_info()
        logger.info(f"Connected to: {info}")
        
        # Try to get art info to test full API access
        art = tv.art()
        available = art.available()
        available_count = len(available)
        
        # Check if token was created
        token_exists = TOKEN_FILE.exists()
        
        return jsonify({
            'success': True,
            'message': f'Successfully connected to {info.get("name", "Samsung TV")}',
            'device_info': info,
            'art_count': available_count,
            'token_created': token_exists,
            'token_file': str(TOKEN_FILE)
        })
        
    except Exception as e:
        error_msg = str(e)
        logger.error(f"TV pairing/connection error: {e}")
        
        # Check if this looks like a pairing issue
        if "Connection refused" in error_msg:
            return jsonify({
                'error': 'Connection refused',
                'instructions': [
                    '1. Make sure your Samsung TV is ON (not standby)',
                    '2. TV must be connected to the same network',
                    '3. TV must support SmartThings API (2016+ models)',
                    '4. Try again - a popup should appear on TV asking to allow connection'
                ],
                'token_exists': TOKEN_FILE.exists()
            })
        elif "timeout" in error_msg.lower():
            return jsonify({
                'error': 'Connection timeout',
                'instructions': [
                    '1. Check if TV IP address is correct',
                    '2. Ensure TV and computer are on same network',
                    '3. Check if TV firewall is blocking port 8002'
                ],
                'token_exists': TOKEN_FILE.exists()
            })
        else:
            return jsonify({
                'error': f'Connection error: {error_msg}',
                'instructions': [
                    '1. Check TV settings and ensure SmartThings/API access is enabled',
                    '2. Try turning TV off and on',
                    '3. Check network connectivity'
                ],
                'token_exists': TOKEN_FILE.exists()
            })

@app.route('/force-pair')
def force_pair():
    """Force pairing process with TV to create token"""
    config = load_config()
    
    # Remove existing token if it exists
    if TOKEN_FILE.exists():
        TOKEN_FILE.unlink()
        logger.info("Removed existing token file")
    
    try:
        logger.info(f"Attempting to force pair with TV at {config['tv_ip']}")
        
        # Try different connection approaches for token creation
        from samsungtvws import SamsungTVWS
        
        # Method 1: Try with name parameter for pairing
        logger.info("Method 1: Connection with name for pairing...")
        tv = SamsungTVWS(
            host=config['tv_ip'], 
            port=8002, 
            token_file=str(TOKEN_FILE),
            name="Frame Art Manager"  # Add name for pairing
        )
        
        # Force operations that should require token
        logger.info("Getting device info...")
        info = tv.rest_device_info()
        
        logger.info("Accessing art API...")
        art = tv.art()
        
        logger.info("Getting available art...")
        available = art.available()
        
        logger.info("Getting current art...")
        current = art.get_current()
        
        # Try a more aggressive operation - upload a tiny test image
        logger.info("Testing upload capability with tiny image...")
        test_pixel = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\tpHYs\x00\x00\x0b\x13\x00\x00\x0b\x13\x01\x00\x9a\x9c\x18\x00\x00\x00\nIDAT\x08\x1dc\xf8\x00\x00\x00\x01\x00\x01\x02\x9aX\xc6\x00\x00\x00\x00IEND\xaeB`\x82'
        try:
            art.upload(test_pixel, file_type='png')
            logger.info("Test upload successful")
        except Exception as upload_e:
            logger.warning(f"Test upload failed: {upload_e}")
        
        # Check if token was created
        token_exists = TOKEN_FILE.exists()
        logger.info(f"Token file exists after operations: {token_exists}")
        
        token_content = ""
        if token_exists:
            with open(TOKEN_FILE, 'r') as f:
                token_content = f.read().strip()
                logger.info(f"Token created: {token_content}")
        else:
            # Try to manually create a connection session
            logger.info("Attempting manual token creation...")
            try:
                # Force a WebSocket connection
                tv.open()
                logger.info("WebSocket connection opened")
                tv.close()
                logger.info("WebSocket connection closed")
            except Exception as ws_e:
                logger.warning(f"WebSocket connection failed: {ws_e}")
        
        final_token_exists = TOKEN_FILE.exists()
        
        return jsonify({
            'success': True,
            'message': 'TV operations completed',
            'device_name': info.get('name', 'Unknown'),
            'token_created': final_token_exists,
            'token_file_path': str(TOKEN_FILE),
            'token_content': token_content[:50] + '...' if token_content else 'None',
            'available_art_count': len(available),
            'current_art': current
        })
        
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Force pairing error: {e}")
        
        return jsonify({
            'error': error_msg,
            'token_exists': TOKEN_FILE.exists(),
            'instructions': [
                'WATCH YOUR TV SCREEN FOR A POPUP!',
                'The TV should show a dialog asking to allow connection',
                'Use your TV remote to select "Allow" or "Yes"',
                'If no popup appears, try turning TV off/on and retry'
            ]
        })

@app.route('/debug-upload/<filename>')
def debug_upload(filename):
    """Debug image upload to TV with detailed logging"""
    config = load_config()
    
    try:
        # Create connection
        tv = SamsungTVWS(
            host=config['tv_ip'], 
            port=8002, 
            token_file=str(TOKEN_FILE)
        )
        
        image_path = IMAGES_DIR / filename
        if not image_path.exists():
            return jsonify({'error': f'Image not found: {filename}'})

        with open(image_path, 'rb') as f:
            image_data = f.read()

        file_ext = filename.rsplit('.', 1)[1].lower()
        file_type = 'png' if file_ext == 'png' else 'jpg'
        
        # Test basic connection
        device_info = tv.rest_device_info()
        
        # Get art API
        art_api = tv.art()
        
        # Get current art info
        current_art = art_api.get_current()
        available_art = art_api.available()
        
        # Attempt upload
        upload_result = art_api.upload(image_data, file_type=file_type)
        
        return jsonify({
            'success': True,
            'filename': filename,
            'file_size': len(image_data),
            'file_type': file_type,
            'device_name': device_info.get('name', 'Unknown'),
            'current_art_count': len(available_art),
            'upload_result': upload_result,
            'current_art': current_art
        })
        
    except Exception as e:
        return jsonify({
            'error': str(e),
            'filename': filename,
            'tv_ip': config['tv_ip']
        })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5600, debug=True)
