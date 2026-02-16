import os
import random
import string
from flask import Flask, render_template_string, request
from flask_socketio import SocketIO, emit, join_room

app = Flask(__name__)
app.config['SECRET_KEY'] = 'econtroler-super-secret'
# eventlet is recommended for production WebSocket handling
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

sessions = {}

# ==========================================
# FRONTEND: HTML, CSS, and JavaScript
# ==========================================
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Econtroler - Remote Assist</title>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.0.1/socket.io.js"></script>
    <style>
        body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: #121212; color: #fff; text-align: center; padding: 50px; }
        .container { max-width: 600px; margin: 0 auto; background: #1e1e1e; padding: 30px; border-radius: 10px; box-shadow: 0 4px 15px rgba(0,0,0,0.5); }
        h1 { color: #4CAF50; }
        .btn { background: #4CAF50; color: white; border: none; padding: 15px 30px; margin: 10px; font-size: 16px; border-radius: 5px; cursor: pointer; transition: 0.3s; }
        .btn:hover { background: #45a049; }
        input[type="text"] { padding: 15px; font-size: 16px; border-radius: 5px; border: none; margin-bottom: 10px; width: 80%; text-align: center; letter-spacing: 2px;}
        video { width: 100%; max-width: 800px; border: 2px solid #4CAF50; border-radius: 5px; margin-top: 20px; background: #000; }
        #code-display { font-size: 32px; font-weight: bold; letter-spacing: 5px; color: #4CAF50; margin: 20px 0; }
        .hidden { display: none; }
    </style>
</head>
<body>

    <div class="container" id="main-menu">
        <h1>Econtroler</h1>
        <p>Do you need help, or are you helping someone?</p>
        <button class="btn" onclick="showGiveOver()">Give Over (Share Screen)</button>
        <button class="btn" onclick="showTakeover()">Takeover (Control Screen)</button>
    </div>

    <div class="container hidden" id="give-over-ui">
        <h2>Your Assistance Code</h2>
        <div id="code-display">Loading...</div>
        <p>Give this code to the person helping you.</p>
        <video id="local-video" autoplay muted></video>
        <br>
        <button class="btn" onclick="resetUI()">Cancel</button>
    </div>

    <div class="container hidden" id="takeover-ui">
        <h2>Enter Code</h2>
        <input type="text" id="join-code" placeholder="Enter 6-digit code" maxlength="6">
        <br>
        <button class="btn" onclick="joinSession()">Connect</button>
        <button class="btn" onclick="resetUI()">Cancel</button>
        <p id="takeover-status"></p>
    </div>

    <div class="hidden" id="remote-view-ui">
        <h2>Remote Control Active</h2>
        <video id="remote-video" autoplay></video>
        <br>
        <button class="btn" onclick="resetUI()">Disconnect</button>
    </div>

    <script>
        const socket = io();
        let peerConnection;
        let dataChannel;
        let localStream;
        let roomCode;
        let isHost = false;

        const config = {
            'iceServers': [{ 'urls': 'stun:stun.l.google.com:19302' }]
        };

        // UI Toggles
        function showGiveOver() {
            document.getElementById('main-menu').classList.add('hidden');
            document.getElementById('give-over-ui').classList.remove('hidden');
            isHost = true;
            startSharing();
        }

        function showTakeover() {
            document.getElementById('main-menu').classList.add('hidden');
            document.getElementById('takeover-ui').classList.remove('hidden');
            isHost = false;
        }

        function resetUI() {
            document.getElementById('main-menu').classList.remove('hidden');
            document.getElementById('give-over-ui').classList.add('hidden');
            document.getElementById('takeover-ui').classList.add('hidden');
            document.getElementById('remote-view-ui').classList.add('hidden');
            if (localStream) localStream.getTracks().forEach(track => track.stop());
            if (peerConnection) peerConnection.close();
            socket.emit('leave');
        }

        // Host Logic: Get Screen and Generate Code
        async function startSharing() {
            try {
                localStream = await navigator.mediaDevices.getDisplayMedia({ video: true });
                document.getElementById('local-video').srcObject = localStream;
                socket.emit('generate_code');
            } catch (err) {
                alert("Screen sharing permission denied.");
                resetUI();
            }
        }

        socket.on('code_generated', (data) => {
            roomCode = data.code;
            document.getElementById('code-display').innerText = roomCode;
        });

        // Controller Logic: Join Room
        function joinSession() {
            const code = document.getElementById('join-code').value;
            if(code.length === 6) {
                roomCode = code;
                document.getElementById('takeover-status').innerText = "Connecting...";
                socket.emit('join_session', { code: roomCode });
            }
        }

        socket.on('session_joined', (data) => {
            if(data.success) {
                document.getElementById('takeover-ui').classList.add('hidden');
                document.getElementById('remote-view-ui').classList.remove('hidden');
            } else {
                document.getElementById('takeover-status').innerText = data.message;
            }
        });

        // WebRTC Signaling Process
        socket.on('controller_connected', async () => {
            // Host creates the peer connection when controller joins
            createPeerConnection();
            localStream.getTracks().forEach(track => peerConnection.addTrack(track, localStream));
            
            // Create data channel for receiving control inputs
            dataChannel = peerConnection.createDataChannel("control");
            setupDataChannel(dataChannel);

            const offer = await peerConnection.createOffer();
            await peerConnection.setLocalDescription(offer);
            socket.emit('webrtc_offer', { code: roomCode, offer: offer });
        });

        socket.on('webrtc_offer', async (data) => {
            if(!isHost) {
                createPeerConnection();
                
                // Controller listens for data channel
                peerConnection.ondatachannel = (event) => {
                    dataChannel = event.channel;
                    setupDataChannel(dataChannel);
                };

                await peerConnection.setRemoteDescription(new RTCSessionDescription(data.offer));
                const answer = await peerConnection.createAnswer();
                await peerConnection.setLocalDescription(answer);
                socket.emit('webrtc_answer', { code: roomCode, answer: answer });
            }
        });

        socket.on('webrtc_answer', async (data) => {
            if(isHost) {
                await peerConnection.setRemoteDescription(new RTCSessionDescription(data.answer));
            }
        });

        socket.on('webrtc_ice_candidate', async (data) => {
            try {
                if (peerConnection) {
                    await peerConnection.addIceCandidate(new RTCIceCandidate(data.candidate));
                }
            } catch (e) {
                console.error('Error adding received ice candidate', e);
            }
        });

        function createPeerConnection() {
            peerConnection = new RTCPeerConnection(config);
            
            peerConnection.onicecandidate = event => {
                if (event.candidate) {
                    socket.emit('webrtc_ice_candidate', { code: roomCode, candidate: event.candidate });
                }
            };

            peerConnection.ontrack = event => {
                // Display the remote screen for the controller
                if(!isHost) {
                    document.getElementById('remote-video').srcObject = event.streams[0];
                }
            };
        }

        function setupDataChannel(channel) {
            channel.onmessage = (event) => {
                if(isHost) {
                    // Log the incoming control coordinates to the console
                    console.log("Input received from controller:", event.data);
                }
            };
        }

        // Capture Controller Mouse Clicks and send over Data Channel
        document.getElementById('remote-video').addEventListener('mousedown', (e) => {
            if (!isHost && dataChannel && dataChannel.readyState === 'open') {
                const rect = e.target.getBoundingClientRect();
                const x = e.clientX - rect.left;
                const y = e.clientY - rect.top;
                const command = JSON.stringify({ action: 'click', x: x, y: y });
                dataChannel.send(command);
            }
        });

    </script>
</body>
</html>
"""

# ==========================================
# BACKEND: Flask & Socket.io Logic
# ==========================================

def generate_6_digit_code():
    return ''.join(random.choices(string.digits, k=6))

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@socketio.on('generate_code')
def handle_generate_code():
    code = generate_6_digit_code()
    while code in sessions:
        code = generate_6_digit_code()
    
    sessions[code] = request.sid
    join_room(code)
    emit('code_generated', {'code': code})

@socketio.on('join_session')
def handle_join_session(data):
    code = data.get('code')
    if code in sessions:
        join_room(code)
        emit('session_joined', {'success': True}, to=request.sid)
        emit('controller_connected', room=sessions[code], skip_sid=request.sid)
    else:
        emit('session_joined', {'success': False, 'message': 'Invalid code.'}, to=request.sid)

@socketio.on('webrtc_offer')
def handle_webrtc_offer(data):
    emit('webrtc_offer', data, room=data['code'], skip_sid=request.sid)

@socketio.on('webrtc_answer')
def handle_webrtc_answer(data):
    emit('webrtc_answer', data, room=data['code'], skip_sid=request.sid)

@socketio.on('webrtc_ice_candidate')
def handle_ice_candidate(data):
    emit('webrtc_ice_candidate', data, room=data['code'], skip_sid=request.sid)

@socketio.on('disconnect')
def handle_disconnect():
    for code, sid in list(sessions.items()):
        if sid == request.sid:
            del sessions[code]

if __name__ == '__main__':
    # Railway passes the assigned port in the PORT environment variable
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host='0.0.0.0', port=port)
