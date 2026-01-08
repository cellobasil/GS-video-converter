import os
import math
import ffmpeg
import logging

logger = logging.getLogger(__name__)

def get_video_info(path):
    try:
        probe = ffmpeg.probe(path)
        video_stream = next((stream for stream in probe['streams'] if stream['codec_type'] == 'video'), None)
        duration = float(probe['format']['duration'])
        return video_stream, duration
    except ffmpeg.Error as e:
        logger.error(f"FFmpeg probe error: {e.stderr.decode() if e.stderr else str(e)}")
        return None, None

def compress_video(input_path, output_path, target_size_mb=12):
    video_stream, duration = get_video_info(input_path)
    if not duration:
        return False, "Could not determine video duration."
    
    # Final Requirement: 12MB limit for Crystal HD quality
    target_size_mb = 12
    target_video_bits = target_size_mb * 8 * 1024 * 1024
    target_video_bitrate = target_video_bits / duration
    
    try:
        if os.path.exists(input_path):
             size_mb = os.path.getsize(input_path) / (1024 * 1024)
             if size_mb <= target_size_mb:
                  logger.info(f"File small enough ({size_mb:.2f}MB). Muting only...")
                  (
                      ffmpeg
                      .input(input_path)
                      .output(output_path, vcodec='copy', an=None)
                      .overwrite_output()
                      .run(capture_stdout=True, capture_stderr=True)
                  )
                  return True, None

        logger.info(f"Encoding 1080p HD (12MB Target)...")
        
        # 1. Attempt GPU Acceleration first (if available)
        try:
            (
                 ffmpeg
                .input(input_path)
                .filter('scale', 'min(1920,iw)', -2)
                .output(
                    output_path, 
                    vcodec='h264_nvenc', 
                    cq=24, qmin=24, qmax=26,
                    maxrate=f'{int(target_video_bitrate)}', 
                    bufsize=f'{int(target_video_bitrate*2)}', 
                    an=None, preset='p1', tune='ll'
                )
                .overwrite_output()
                .run(capture_stdout=True, capture_stderr=True)
            )
            return True, None
        except ffmpeg.Error:
            logger.warning("NVENC failed or not available. Falling back to CPU (libx264)...")
            if os.path.exists(output_path): os.remove(output_path)
            
            # 2. Server Fallback: High-performance CPU Encoding
            (
                 ffmpeg
                .input(input_path)
                .filter('scale', 'min(1920,iw)', -2)
                .output(
                    output_path, 
                    vcodec='libx264', 
                    crf=24,
                    maxrate=f'{int(target_video_bitrate)}', 
                    bufsize=f'{int(target_video_bitrate*2)}', 
                    an=None, 
                    preset='ultrafast', # Max speed for server
                    tune='fastdecode', # Optimized for fast decoding/encoding
                    threads=2 # Limit to 2 threads per FFmpeg (since we run 2 FFmpegs on 4 cores)
                )
                .overwrite_output()
                .run(capture_stdout=True, capture_stderr=True)
            )
            return True, None
            
    except ffmpeg.Error as e:
        err = e.stderr.decode() if e.stderr else str(e)
        logger.error(f"FFmpeg error: {err}")
        return False, err

def compress_photo(input_path, output_path, target_size_mb=4.8):
    try:
        (
            ffmpeg
            .input(input_path)
            .output(output_path, qscale=2)
            .overwrite_output()
            .run(capture_stdout=True, capture_stderr=True)
        )
        return True, None
    except ffmpeg.Error as e:
        return False, str(e)
