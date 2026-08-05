import argparse
import pyttsx3

def voice(text):
    # 初始化 pyttsx3 引擎
    engine = pyttsx3.init()

    # 设置语音的参数（可选）
    engine.setProperty('rate', 150)  # 语速
    engine.setProperty('volume', 1.0)  # 音量 (0.0 到 1.0)

    engine.say(text)
    engine.runAndWait()

if __name__ == '__main__':
    parser = argparse.ArgumentParser()

    parser.add_argument('--text', type=str, default='Hello World', help='Text to speak')

    args = parser.parse_args()
    
    voice(args.text)