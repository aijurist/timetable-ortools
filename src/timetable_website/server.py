#!/usr/bin/env python3
import http.server
import socketserver
import os
import urllib.parse
from pathlib import Path

class TimetableHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=os.path.dirname(os.path.abspath(__file__)), **kwargs)
    
    def end_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        super().end_headers()
    
    def do_GET(self):
        if self.path == '/api/csv-data':
            self.serve_csv_data()
        else:
            super().do_GET()
    
    def serve_csv_data(self):
        try:
            # Look for CSV file in the output directory
            csv_path = Path(__file__).parent.parent.parent / "output" / "lab_schedule_20250529_125226" / "combined_theory_lab_schedule.csv"
            
            if csv_path.exists():
                with open(csv_path, 'r', encoding='utf-8') as f:
                    csv_content = f.read()
                
                self.send_response(200)
                self.send_header('Content-Type', 'text/csv')
                self.end_headers()
                self.wfile.write(csv_content.encode('utf-8'))
            else:
                self.send_response(404)
                self.send_header('Content-Type', 'text/plain')
                self.end_headers()
                self.wfile.write(b'CSV file not found')
                
        except Exception as e:
            self.send_response(500)
            self.send_header('Content-Type', 'text/plain')
            self.end_headers()
            self.wfile.write(f'Error reading CSV: {str(e)}'.encode('utf-8'))

def run_server(port=8000):
    try:
        with socketserver.TCPServer(("", port), TimetableHandler) as httpd:
            print(f"🌟 Timetable Management Website Server")
            print(f"📂 Serving from: {os.path.dirname(os.path.abspath(__file__))}")
            print(f"🌐 Open your browser and go to: http://localhost:{port}")
            print(f"📊 CSV data available at: http://localhost:{port}/api/csv-data")
            print(f"🛑 Press Ctrl+C to stop the server")
            print("-" * 60)
            httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n👋 Server stopped by user")
    except OSError as e:
        if "Address already in use" in str(e):
            print(f"❌ Port {port} is already in use. Try a different port:")
            print(f"   python server.py {port + 1}")
        else:
            print(f"❌ Error starting server: {e}")

if __name__ == "__main__":
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    run_server(port) 