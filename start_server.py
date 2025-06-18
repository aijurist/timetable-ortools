#!/usr/bin/env python3
"""
Simple HTTP Server for University Timetable Schedule Website

This script starts a local HTTP server to serve the schedule website.
Run this script and then open http://localhost:8000 in your browser.
"""

import http.server
import socketserver
import webbrowser
import os
import sys
import glob
import json
from pathlib import Path

def find_latest_schedule_folder():
    """Find the latest combined_schedule folder."""
    pattern = "output/combined_schedule_*"
    folders = glob.glob(pattern)
    if not folders:
        return None
    # Sort by folder name (which includes timestamp) and get the latest
    latest_folder = sorted(folders)[-1]
    return latest_folder

def start_server():
    """Start the HTTP server."""
    PORT = 8000
    
    # Change to the directory containing this script
    script_dir = Path(__file__).parent.absolute()
    os.chdir(script_dir)
    
    # Find the latest schedule folder
    latest_folder = find_latest_schedule_folder()
    if not latest_folder:
        print("❌ Error: No combined_schedule folders found in output directory.")
        print("   Please run the timetable scheduler first to generate schedules.")
        return False
    
    print(f"📁 Using latest schedule folder: {latest_folder}")
    
    # Check if required files exist
    required_files = [
        'schedule_website.html',
        'schedule_viewer.js',
        f'{latest_folder}/combined_lab_schedule.json',
        f'{latest_folder}/combined_theory_schedule.json'
    ]
    
    missing_files = []
    for file_path in required_files:
        if not os.path.exists(file_path):
            missing_files.append(file_path)
    
    if missing_files:
        print("❌ Error: Missing required files:")
        for file_path in missing_files:
            print(f"   - {file_path}")
        print("\nPlease ensure all files are in the correct location.")
        return False
    
    try:
        # Create server
        Handler = http.server.SimpleHTTPRequestHandler
        
        # Enable CORS for local development and inject latest folder path
        class CORSRequestHandler(Handler):
            def end_headers(self):
                self.send_header('Access-Control-Allow-Origin', '*')
                self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
                self.send_header('Access-Control-Allow-Headers', 'Content-Type')
                super().end_headers()
            
            def do_GET(self):
                # Special endpoint to provide the latest folder path
                if self.path == '/api/latest-folder':
                    self.send_response(200)
                    self.send_header('Content-type', 'application/json')
                    self.end_headers()
                    latest = find_latest_schedule_folder()
                    if latest:
                        # Use forward slashes for web paths and proper JSON encoding
                        latest_web_path = latest.replace('\\', '/')
                        response_data = {"latestFolder": latest_web_path}
                    else:
                        response_data = {"error": "No schedule folder found"}
                    
                    # Use proper JSON encoding to avoid escape character issues
                    response = json.dumps(response_data)
                    self.wfile.write(response.encode())
                    return
                
                # Default behavior for other requests
                super().do_GET()
        
        with socketserver.TCPServer(("", PORT), CORSRequestHandler) as httpd:
            print(f"🚀 Starting University Timetable Schedule Website")
            print(f"📁 Serving from: {script_dir}")
            print(f"🌐 Server running at: http://localhost:{PORT}")
            print(f"📄 Website URL: http://localhost:{PORT}/schedule_website.html")
            print(f"🔄 Latest folder API: http://localhost:{PORT}/api/latest-folder")
            print(f"\n💡 Press Ctrl+C to stop the server")
            
            # Try to open browser automatically
            try:
                webbrowser.open(f'http://localhost:{PORT}/schedule_website.html')
                print("🔗 Opening website in your default browser...")
            except Exception as e:
                print(f"⚠️  Could not open browser automatically: {e}")
                print(f"   Please manually open: http://localhost:{PORT}/schedule_website.html")
            
            print("\n" + "="*60)
            
            # Start serving
            httpd.serve_forever()
            
    except KeyboardInterrupt:
        print(f"\n\n🛑 Server stopped by user")
        return True
    except OSError as e:
        if e.errno == 48:  # Address already in use
            print(f"❌ Error: Port {PORT} is already in use.")
            print(f"   Please stop any other servers running on port {PORT} or")
            print(f"   modify the PORT variable in this script.")
        else:
            print(f"❌ Error starting server: {e}")
        return False
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return False

def main():
    """Main entry point."""
    print("University Timetable Schedule Website Server")
    print("=" * 50)
    
    if len(sys.argv) > 1 and sys.argv[1] in ['-h', '--help']:
        print(__doc__)
        print("\nUsage:")
        print("  python start_server.py")
        print("\nThis will start a local HTTP server and open the website in your browser.")
        return
    
    success = start_server()
    if not success:
        sys.exit(1)

if __name__ == "__main__":
    main() 