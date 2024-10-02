from flask import Flask, request, jsonify, send_file
import numpy as np
import requests
import base64
import os
import tempfile
from moviepy.editor import ImageClip, concatenate_videoclips, AudioFileClip
from moviepy.video.fx.all import resize
from PIL import Image
import io

app = Flask(__name__)

# Function to download the image from the URL
def download_image(url):
    response = requests.get(url)
    response.raise_for_status()  # Raise an error for bad responses
    img = Image.open(io.BytesIO(response.content))
    return img

# Function to create audio from text using Speechify API
def speak(paragraph: str, voice_name: str = "mrbeast"):
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
    response.raise_for_status()  # Raise an error for bad responses

    audio_data = base64.b64decode(response.json()['audioStream'])
    return audio_data

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
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as img_file:
            img.save(img_file.name)
            img_path = img_file.name

        # Create an audio file from the content text using Speechify
        audio_data = speak(scene['contentText'], voice_name)
        
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as audio_file:
            audio_file.write(audio_data)
            audio_file_path = audio_file.name

        # Create an ImageClip from the saved image and set its duration
        img_clip = ImageClip(img_path)
        
        # Load the audio clip
        audio_clip = AudioFileClip(audio_file_path)
        
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
    for img_clip in video_clips:
        img_clip.reader.close()  # Close the image clip reader to free resources
    os.remove(img_path)
    os.remove(audio_file_path)

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
