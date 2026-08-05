from flask import Flask, request
import subprocess
import os

app = Flask(__name__)

@app.route('/receive_message', methods=['POST'])
def receive_message():
    data = request.get_json()
    text = data['message']
    print('Received:', text)
    if text != '':
        try:
            current_dir = os.getcwd()
            script_path = os.path.join(current_dir, 'voice.py')
            subprocess.Popen(['python', script_path, '--text', text])
            return 'Script voice.py started', 200
        except Exception as e:
            return f"Error starting script: {str(e)}", 500
    else:
        return RuntimeError('Invalid command'), 400

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)