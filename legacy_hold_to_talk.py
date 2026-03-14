import os
import signal  # for keyboard events handling (press "Ctrl+C" to terminate recording)
import sys
import threading
import time
import os
import signal  # for keyboard events handling (press "Ctrl+C" to terminate recording)
import sys
import threading
import time

import dashscope
import pyaudio
from dashscope.audio.asr import Recognition, RecognitionCallback, RecognitionResult
from pynput import keyboard
from text_format import TextGenerator
import pyperclip
import pyautogui
# Set recording parameters
SAMPLE_RATE = 16000  # sampling rate (Hz)
CHANNELS = 1  # mono channel
DTYPE = 'int16'  # data type
FORMAT_PCM = 'pcm'  # the format of the audio data
BLOCK_SIZE = 3200  # number of frames per buffer

DEFAULT_MESSAGE = [
    {"role": "system", "content": "用户口述文本发给你，你首先理解用户真实意图，尽量不更改口述文本的情况下，输出用户真实意图的文本。"},
    {"role": "user", "content": "待定义"},
]

CHAT_MESSAGE = [
    {"role": "system", "content": "用户口述文本发给你，你首先理解用户真实意图，根据用户的真实意图，优化用户口述文本。"},
    {"role": "user", "content": "待定义"},
]
EMAIL_MESSAGE = [
    {"role": "system", "content": "你是邮件助手，能够对邮件内容进行润色。我的个人信息如下：姓名：胡进森，邮箱是：<hujsen@163.com>,电话是：13290818863，个人网站是：https://hujinsen.github.io/。"},
    {"role": "user", "content": "待定义"},
]

CODE_MESSAGE = [
    {"role": "system", "content": "你是编程助手，理解用户输入内容的语义，输出能表达用户真实诉求的文本"},
    {"role": "user", "content": "待定义"},
]

def init_dashscope_api_key():
    """Set DashScope API key from environment or inline value."""
    if 'DASHSCOPE_API_KEY' in os.environ:
        dashscope.api_key = os.environ['DASHSCOPE_API_KEY']
    else:
        dashscope.api_key = 'sk-2d627fbbc4fa491db207c632a77f2852'


class HoldToTalkRecognizer:
    """Encapsulates hold-to-talk behavior using DashScope recognition.

    Usage: create instance and call run(). Press and hold Left Alt to start a session,
    release to stop and print results. Program stays running for more sessions.
    """

    def __init__(self):
        init_dashscope_api_key()
        self._mic = None
        self._stream = None
        self._recognition = None
        self._callback = None
        self._audio_thread = None
        self._running = False
        self._results_lock = threading.Lock()
        self._format_text = TextGenerator(api_key=dashscope.api_key)


        
    class _Callback(RecognitionCallback):
        def __init__(self, owner: 'HoldToTalkRecognizer'):
            super().__init__()
            self.owner = owner

        def on_open(self) -> None:
            # open mic and stream for this session
            print('RecognitionCallback open.')
            self.owner._mic = pyaudio.PyAudio()
            self.owner._stream = self.owner._mic.open(format=pyaudio.paInt16,
                                                      channels=CHANNELS,
                                                      rate=SAMPLE_RATE,
                                                      input=True)

        def on_close(self) -> None:
            print('RecognitionCallback close.')
            if self.owner._stream is not None:
                try:
                    self.owner._stream.stop_stream()
                except Exception:
                    pass
                try:
                    self.owner._stream.close()
                except Exception:
                    pass
            if self.owner._mic is not None:
                try:
                    self.owner._mic.terminate()
                except Exception:
                    pass
            self.owner._stream = None
            self.owner._mic = None

        def on_complete(self) -> None:
            print('RecognitionCallback completed.')

        def on_error(self, message) -> None:
            print('RecognitionCallback task_id: ', getattr(message, 'request_id', None))
            print('RecognitionCallback error: ', getattr(message, 'message', None))
            # terminate session on error
            try:
                if self.owner._stream is not None:
                    try:
                        if hasattr(self.owner._stream, 'is_active') and self.owner._stream.is_active():
                            self.owner._stream.stop_stream()
                    except Exception:
                        pass
                    try:
                        self.owner._stream.close()
                    except Exception:
                        pass
            finally:
                # not exiting the program; allow user to continue
                self.owner._running = False

        def on_event(self, result: RecognitionResult) -> None:
            try:
                sentence = result.get_sentence()
                # print('DEBUG on_event received sentence:', repr(sentence))
                if sentence is None:
                    return
                # handle different possible shapes defensively
                text = None
                if isinstance(sentence, dict) and 'text' in sentence:
                    text = sentence['text']
                elif isinstance(sentence, list) and len(sentence) > 0:
                    # sometimes api may return a list; attempt to find a dict with 'text'
                    for item in sentence:
                        if isinstance(item, dict) and 'text' in item:
                            text = item['text']
                            break
                if text is None:
                    return
                if RecognitionResult.is_sentence_end(sentence):
                    try:
                        print('RecognitionCallback sentence end, request_id:%s, usage:%s' % (
                            result.get_request_id(), result.get_usage(sentence)))
                    except Exception:
                        print('DEBUG: failed to print request/usage')
                    with self.owner._results_lock:
                        if not hasattr(self.owner, '_results'):
                            self.owner._results = []
                        self.owner._results.append(text)
                        print('DEBUG appended text ->', repr(text))
            except Exception as e:
                print('DEBUG on_event exception:', e)


    def _audio_sender(self):
        while self._running:
            try:
                if self._stream:
                    data = self._stream.read(BLOCK_SIZE, exception_on_overflow=False)
                    if self._recognition is not None:
                        self._recognition.send_audio_frame(data)
                else:
                    print("音频流未打开！")
                    time.sleep(0.01)
            except Exception as e:
                print(f"读取音频或发送音频帧时出错：{e}")
                if not self._running:  # 如果已经停止，直接退出循环
                    break
                time.sleep(0.01)


    def start_session(self):
        if self._running:
            return
        print('Start recognition session')
        self._callback = HoldToTalkRecognizer._Callback(self)
        self._recognition = Recognition(
            model='fun-asr-realtime',
            format=FORMAT_PCM,
            sample_rate=SAMPLE_RATE,
            semantic_punctuation_enabled=False,
            callback=self._callback
        )
        try:
            self._recognition.start()
            self._running = True
            # clear previous results
            with self._results_lock:
                self._results = []
            self._audio_thread = threading.Thread(target=self._audio_sender, daemon=True)
            self._audio_thread.start()
        except Exception as e:
            print('Failed to start recognition:', e)
            self._running = False

    def stop_session(self):
        # if not self._running:
        #     return
        # print('Stop recognition session')
        # try:
        #     if self._recognition is not None:
        #         self._recognition.stop()
        # except Exception as e:
        #     print('Failed to stop recognition:', e)
        # wait for callbacks to finish appending results

        if not self._running:
            return
        print('Stop recognition session')
        self._running = False  # 先停止线程循环
        if self._audio_thread is not None:
            self._audio_thread.join()  # 等待线程结束
        if self._recognition is not None:
            self._recognition.stop()  # 停止识别
        if self._stream is not None:
            try:
                self._stream.stop_stream()
                self._stream.close()
            except Exception:
                pass
        if self._mic is not None:
            try:
                self._mic.terminate()
            except Exception:
                pass
        self._stream = None
        self._mic = None
        self._recognition = None
        self._audio_thread = None
        self._callback = None
        self._running = False   
                    
        # print results
        with self._results_lock:
            results = getattr(self, '_results', [])
            
            if results:
                final_text = ' '.join(results)
                print('Final recognition result:\n' + final_text)
                # format text using TextGenerator
                messages = DEFAULT_MESSAGE.copy()
                # messages = EMAIL_MESSAGE.copy()
                # messages = CODE_MESSAGE.copy()
                # replace placeholder with actual recognized text
                messages[-1]['content'] = final_text
                print('使用模版提示词:', messages)
                formatted = self._format_text.generate(messages)
                print('Formatted response:', repr(formatted))
                if formatted:
                    formatted_content = formatted.get("output", {}).get("choices", [])[0].get("message", {}).get("content", "")
                    print('Formatted text:\n' + formatted_content)
                    #将格式化后文本写入当前活动光标处
                    # 将文本复制到剪贴板
                    pyperclip.copy(formatted_content)

                    # 模拟粘贴操作
                    pyautogui.hotkey("ctrl", "v")
                    # pyautogui.write(formatted_content)
                else:
                    print('No formatted response received.')

            else:
                print('No final recognition result.')
            # clear
            self._results = []
        # cleanup
        # self._recognition = None
        # self._callback = None
        # self._running = False

    def shutdown(self):
        # stop any running session
        if self._running and self._recognition is not None:
            try:
                self._recognition.stop()
            except Exception:
                pass
        print('Shutting down')

    def run(self):
        # set up signal handler to allow graceful exit
        def _signal_handler(sig, frame):
            print('Ctrl+C pressed')
            self.shutdown()
            sys.exit(0)

        signal.signal(signal.SIGINT, _signal_handler)
        print("Initializing ... Hold Left Alt (opt) to talk, release to stop and show result. Press Ctrl+C to quit.")

        def on_press(key):
            try:
                if key == keyboard.Key.ctrl_l or (key == keyboard.Key.space and 'ctrl_l' in pressed_keys):
                    if not self._running:
                        self.start_session()
                
                #t
                # 同时按下ctrl和C键，停止识别shutdown并退出
                
                if 'ctrl_l' in pressed_keys and 'c' in pressed_keys:
                    print('Ctrl+C detected')
                    self.shutdown()
                    sys.exit(0)
               
            except Exception:
                pass

        def on_release(key):
            try:
                if key == keyboard.Key.ctrl_l or (key == keyboard.Key.space and 'ctrl_l' in pressed_keys):
                    if self._running:
                        self.stop_session()
            except Exception:
                pass

        # start keyboard listener (blocking)
        with keyboard.Listener(on_press=on_press, on_release=on_release, daemon=True) as listener:
            listener.join()


if __name__ == '__main__':
    app = HoldToTalkRecognizer()
    app.run()