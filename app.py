from flask import Flask, request, jsonify, send_file
import cv2
import numpy as np
import requests
import base64
import os
from moviepy.editor import ImageClip, concatenate_videoclips, AudioFileClip
from moviepy.video.fx.all import resize  # Correct import for resize effect

app = Flask(__name__)

# Function to download the image from the URL
def download_image(url):
    response = requests.get(url)
    img_array = np.asarray(bytearray(response.content), dtype=np.uint8)
    img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
    return img

# Function to create audio from text using Speechify API
def speak(paragraph: str, voice_name: str = "mrbeast", filename: str = "output_audio.mp3"):
    try: os.remove(filename)
    except: pass

    url = "https://audio.api.speechify.com/generateAudioFiles"
    payload = {
        "audioFormat": "mp3",
        "paragraphChunks": [paragraph],
        "voiceParams": {
            "name": voice_name,
            "engine": "speechify",
            "languageCode": "en-US"
        }
    }

    response = requests.post(url, json=payload)
    response.raise_for_status()
    
    audio_data = base64.b64decode(response.json()['audioStream'])
    with open(filename, 'wb') as audio_file:
        audio_file.write(audio_data)

# Function to add a slight zoom-in effect to an image clip
def apply_zoom_effect(clip, zoom_factor=1.05):
    return clip.fx(resize, lambda t: 1 + zoom_factor * t / clip.duration)

# Main function to create the video
def create_video(scenes, voice_name="mrbeast"):
    video_clips = []
    
    for idx, scene in enumerate(scenes):
        # Download image
        img_url = f"https://image.pollinations.ai/prompt/{scene['imagePrompt']}?width=1080&height=1920"
        img = download_image(img_url)

        # Save the image temporarily for MoviePy to load
        img_path = f"temp_image_{idx}.png"
        cv2.imwrite(img_path, img)

        # Create an audio file from the content text using Speechify
        audio_file = f"audio_{idx}.mp3"
        speak(scene['contentText'], voice_name, audio_file)

        # Create an ImageClip from the saved image and set its duration
        img_clip = ImageClip(img_path)
        
        # Load the audio clip
        audio_clip = AudioFileClip(audio_file)
        
        # Set the image clip duration to the length of the audio clip
        img_clip = img_clip.set_duration(audio_clip.duration)

        # Apply zoom-in effect
        img_clip = apply_zoom_effect(img_clip)

        # Set the audio for the image clip
        img_clip = img_clip.set_audio(audio_clip)

        # Append to the video clip list
        video_clips.append(img_clip)

    # Concatenate all the clips into one video
    final_video = concatenate_videoclips(video_clips, method="compose")

    # Write the final video to a file
    final_video_path = "output_video.mp4"
    final_video.write_videofile(final_video_path, fps=24)

    # Clean up temporary files
    for idx in range(len(scenes)):
        os.remove(f"temp_image_{idx}.png")
        os.remove(f"audio_{idx}.mp3")
    
    return final_video_path

@app.route('/generate_video', methods=['POST'])
def generate_video():
    data = request.get_json()

    # Extract voice name and scene prompts from the request
    voice_name = data.get('voice_name', 'mrbeast')
    scenes = data.get('scenes', [])

    if not scenes:
        return jsonify({"error": "No scenes provided"}), 400

    # Create the video
    video_file_path = create_video(scenes, voice_name)

    # Respond with the video file for download
    return send_file(video_file_path, as_attachment=True)

if __name__ == '__main__':
    app.run(debug=True)
