import requests
import time
import json
import argparse
import sys
from flask import Flask, render_template_string, request, jsonify
import threading
from datetime import datetime
import re

try:
    import tkinter as tk
    from tkinter import messagebox, simpledialog
    TKINTER_AVAILABLE = True
except ImportError:
    TKINTER_AVAILABLE = False

app = Flask(__name__)

# Configuration
API_KEY = None
STREAM_URL = None
live_chat_id = None
chat_messages = []
is_running = False

# HTML template for the chat display
CHAT_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>YouTube Live Chat</title>
    <style>
        body {
            font-family: 'Segoe UI', Arial, sans-serif;
            margin: 0;
            padding: 20px;
            background: transparent;
            color: white;
            font-size: 18px;
            line-height: 1.4;
        }
        
        .chat-container {
            max-width: 600px;
            max-height: 500px;
            overflow-y: auto;
            background: rgba(0, 0, 0, 0.3);
            border-radius: 10px;
            padding: 15px;
        }
        
        .message {
            margin-bottom: 8px;
            word-wrap: break-word;
        }
        
        .username {
            color: #4A90E2;
            font-weight: bold;
        }
        
        .username.moderator {
            color: #4A90E2;
        }
        
        .username.owner {
            color: #4A90E2;
        }
        
        .message-text {
            color: #00FFFF;
            margin-left: 5px;
        }
        
        .moderator-badge {
            color: #4A90E2;
            font-weight: bold;
        }
        
        .owner-badge {
            color: #4A90E2;
            font-weight: bold;
        }
        
        /* Custom scrollbar */
        .chat-container::-webkit-scrollbar {
            width: 8px;
        }
        
        .chat-container::-webkit-scrollbar-track {
            background: rgba(255, 255, 255, 0.1);
            border-radius: 4px;
        }
        
        .chat-container::-webkit-scrollbar-thumb {
            background: rgba(255, 255, 255, 0.3);
            border-radius: 4px;
        }
        
        .chat-container::-webkit-scrollbar-thumb:hover {
            background: rgba(255, 255, 255, 0.5);
        }
    </style>
</head>
<body>
    <div class="chat-container" id="chatContainer">
        <!-- Messages will be inserted here -->
    </div>
    
    <script>
        function updateChat() {
            fetch('/get_messages')
                .then(response => response.json())
                .then(data => {
                    const container = document.getElementById('chatContainer');
                    const wasAtBottom = container.scrollHeight - container.clientHeight <= container.scrollTop + 1;
                    
                    container.innerHTML = '';
                    data.messages.forEach(message => {
                        const messageDiv = document.createElement('div');
                        messageDiv.className = 'message';
                        
                        let badge = '';
                        let usernameClass = 'username';
                        
                        if (message.is_owner) {
                            badge = ' <span class="owner-badge">(O)</span>';
                            usernameClass += ' owner';
                        } else if (message.is_moderator) {
                            badge = ' <span class="moderator-badge">(M)</span>';
                            usernameClass += ' moderator';
                        }
                        
                        messageDiv.innerHTML = `
                            <span class="${usernameClass}">${message.display_name}${badge}:</span>
                            <span class="message-text">${message.text}</span>
                        `;
                        
                        container.appendChild(messageDiv);
                    });
                    
                    // Auto-scroll to bottom if user was already at bottom
                    if (wasAtBottom) {
                        container.scrollTop = container.scrollHeight;
                    }
                })
                .catch(error => console.error('Error fetching messages:', error));
        }
        
        // Update chat every 2 seconds
        setInterval(updateChat, 2000);
        updateChat(); // Initial load
    </script>
</body>
</html>
"""

def extract_video_id(url):
    """Extract video ID from various YouTube URL formats"""
    patterns = [
        r'(?:youtube\.com/watch\?v=|youtu\.be/)([^&\n?#]+)',
        r'youtube\.com/embed/([^&\n?#]+)',
        r'youtube\.com/v/([^&\n?#]+)'
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None

def get_live_chat_id(video_id):
    """Get the live chat ID from a video ID"""
    url = f"https://www.googleapis.com/youtube/v3/videos"
    params = {
        'part': 'liveStreamingDetails',
        'id': video_id,
        'key': API_KEY
    }
    
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        
        if 'items' in data and len(data['items']) > 0:
            live_details = data['items'][0].get('liveStreamingDetails', {})
            return live_details.get('activeLiveChatId')
        return None
    except Exception as e:
        print(f"Error getting live chat ID: {e}")
        return None

def fetch_chat_messages():
    """Fetch chat messages from YouTube Live Chat API"""
    global chat_messages, is_running, live_chat_id
    
    next_page_token = None
    
    while is_running and live_chat_id:
        try:
            url = "https://www.googleapis.com/youtube/v3/liveChat/messages"
            params = {
                'liveChatId': live_chat_id,
                'part': 'snippet,authorDetails',
                'key': API_KEY
            }
            
            if next_page_token:
                params['pageToken'] = next_page_token
            
            response = requests.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            
            # Process new messages
            new_messages = []
            for item in data.get('items', []):
                snippet = item['snippet']
                author = item['authorDetails']
                
                message = {
                    'display_name': author['displayName'],
                    'text': snippet['displayMessage'],
                    'timestamp': snippet['publishedAt'],
                    'is_moderator': author.get('isChatModerator', False),
                    'is_owner': author.get('isChatOwner', False),
                    'message_id': item['id']
                }
                new_messages.append(message)
            
            # Add new messages to the list (keep last 50 messages)
            chat_messages.extend(new_messages)
            chat_messages = chat_messages[-50:]  # Keep only last 50 messages
            
            # Get next page token and polling interval
            next_page_token = data.get('nextPageToken')
            polling_interval = data.get('pollingIntervalMillis', 5000) / 1000.0
            
            time.sleep(polling_interval)
            
        except Exception as e:
            print(f"Error fetching messages: {e}")
            time.sleep(5)  # Wait 5 seconds before retrying

def get_input_gui():
    """Get API key and stream URL using tkinter GUI"""
    global API_KEY, STREAM_URL
    
    if not TKINTER_AVAILABLE:
        print("Tkinter not available. Use --no-gui flag for terminal input.")
        return False
    
    root = tk.Tk()
    root.withdraw()  # Hide the main window
    
    try:
        # Get API Key
        API_KEY = simpledialog.askstring(
            "YouTube Live Chat - ihts-chatbox", 
            "Enter your YouTube Data API v3 Key:",
            show='*'
        )
        
        if not API_KEY:
            messagebox.showerror("Error", "API Key is required!")
            return False
        
        # Get Stream URL
        STREAM_URL = simpledialog.askstring(
            "YouTube Live Chat - ihts-chatbox", 
            "Enter YouTube Live Stream URL:"
        )
        
        if not STREAM_URL:
            messagebox.showerror("Error", "Stream URL is required!")
            return False
        
        return True
        
    except Exception as e:
        print(f"GUI Error: {e}")
        return False
    finally:
        root.destroy()

def get_input_terminal():
    """Get API key and stream URL using terminal input"""
    global API_KEY, STREAM_URL
    
    print("ihts-chatbox by MalikHw47")
    print("=" * 30)
    
    try:
        API_KEY = input("Enter your YouTube Data API v3 Key: ").strip()
        if not API_KEY:
            print("Error: API Key is required!")
            return False
        
        STREAM_URL = input("Enter YouTube Live Stream URL: ").strip()
        if not STREAM_URL:
            print("Error: Stream URL is required!")
            return False
        
        return True
        
    except KeyboardInterrupt:
        print("\nOperation cancelled.")
        return False

def setup_chat():
    """Setup the chat monitoring"""
    global live_chat_id, is_running, chat_messages
    
    video_id = extract_video_id(STREAM_URL)
    if not video_id:
        print("Error: Invalid YouTube URL")
        return False
    
    live_chat_id = get_live_chat_id(video_id)
    if not live_chat_id:
        print("Error: No live chat found for this video")
        return False
    
    # Reset messages and start fetching
    chat_messages = []
    is_running = True
    
    # Start chat fetching in a separate thread
    chat_thread = threading.Thread(target=fetch_chat_messages)
    chat_thread.daemon = True
    chat_thread.start()
    
    return True

@app.route('/')
def chat_display():
    """Serve the chat display page"""
    return render_template_string(CHAT_HTML)

@app.route('/get_messages')
def get_messages():
    """API endpoint to get current messages"""
    return jsonify({'messages': chat_messages})

@app.route('/start_chat', methods=['POST'])
def start_chat():
    """Start monitoring a YouTube live stream chat"""
    global live_chat_id, is_running, chat_messages
    
    data = request.get_json()
    video_url = data.get('url', '')
    
    if not video_url:
        return jsonify({'error': 'No URL provided'}), 400
    
    video_id = extract_video_id(video_url)
    if not video_id:
        return jsonify({'error': 'Invalid YouTube URL'}), 400
    
    live_chat_id = get_live_chat_id(video_id)
    if not live_chat_id:
        return jsonify({'error': 'No live chat found for this video'}), 400
    
    # Reset messages and start fetching
    chat_messages = []
    is_running = True
    
    # Start chat fetching in a separate thread
    chat_thread = threading.Thread(target=fetch_chat_messages)
    chat_thread.daemon = True
    chat_thread.start()
    
    return jsonify({'success': True, 'message': 'Chat monitoring started'})

@app.route('/stop_chat', methods=['POST'])
def stop_chat():
    """Stop monitoring chat"""
    global is_running
    is_running = False
    return jsonify({'success': True, 'message': 'Chat monitoring stopped'})

def show_help():
    """Show help information"""
    help_text = """
ihts-chatbox by MalikHw47
YouTube Live Chat for OBS

Usage: python youtube_chat_obs.py [OPTIONS]

Options:
  --info      Display project information
  --no-gui    Use terminal input instead of GUI (ideal for TUI environments)
  --help      Show this help message

Setup Instructions:
1. Get YouTube Data API v3 key from Google Cloud Console
2. Install required packages: pip install flask requests tkinter
3. Run this script
4. Enter your API key and stream URL when prompted
5. Open http://localhost:5000 in OBS browser source

The script will automatically start monitoring the specified live stream chat.
"""
    print(help_text)

def show_info():
    """Show project information"""
    info_text = """
Project: ihts-chatbox
Author: MalikHw47
Description: YouTube Live Chat overlay for OBS Studio
Version: 2.0
"""
    print(info_text)

def main():
    parser = argparse.ArgumentParser(description='YouTube Live Chat for OBS', add_help=False)
    parser.add_argument('--info', action='store_true', help='Display project information')
    parser.add_argument('--no-gui', action='store_true', help='Use terminal input instead of GUI')
    parser.add_argument('--help', action='store_true', help='Show help message')
    
    args = parser.parse_args()
    
    if args.help:
        show_help()
        return
    
    if args.info:
        show_info()
        return
    
    # Get input based on flags
    if args.no_gui or not TKINTER_AVAILABLE:
        if not get_input_terminal():
            return
    else:
        if not get_input_gui():
            return
    
    # Setup chat monitoring
    if not setup_chat():
        return
    
    print("\nServer starting...")
    print("Chat display URL: http://localhost:5000")
    print("Chat monitoring started for:", STREAM_URL)
    print("\nPress Ctrl+C to stop")
    
    try:
        app.run(host='0.0.0.0', port=5000, debug=False)
    except KeyboardInterrupt:
        print("\nShutting down...")
        is_running = False

if __name__ == '__main__':
    main()
