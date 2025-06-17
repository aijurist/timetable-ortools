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
from pathlib import Path

def start_server():
    """Start the HTTP server."""
    PORT = 8000
    
    # Change to the directory containing this script
    script_dir = Path(__file__).parent.absolute()
    os.chdir(script_dir)
    
    # Check if required files exist
    required_files = [
        'schedule_website.html',
        'schedule_viewer.js',
        'output/combined_schedule_20250617_133148/combined_lab_schedule.json',
        'output/combined_schedule_20250617_133148/combined_theory_schedule.json'
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
        
        # Enable CORS for local development
        class CORSRequestHandler(Handler):
            def end_headers(self):
                self.send_header('Access-Control-Allow-Origin', '*')
                self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
                self.send_header('Access-Control-Allow-Headers', 'Content-Type')
                super().end_headers()
        
        with socketserver.TCPServer(("", PORT), CORSRequestHandler) as httpd:
            print(f"🚀 Starting University Timetable Schedule Website")
            print(f"📁 Serving from: {script_dir}")
            print(f"🌐 Server running at: http://localhost:{PORT}")
            print(f"📄 Website URL: http://localhost:{PORT}/schedule_website.html")
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