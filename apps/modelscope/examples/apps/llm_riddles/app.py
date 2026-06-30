import functools
import inspect
import os
import random
import re
import tarfile

import gradio as gr
import requests
from challenges.ch1 import challenge1
from challenges.ch2 import challenge2
from challenges.ch3 import challenge3
from challenges.ch4 import challenge4
from challenges.ch5 import challenge5
from llm import create_model
from PIL import Image, ImageDraw, ImageFont

model_cache = {}

# 定义关卡信息和验证逻辑
challenges = [
    challenge1,
    challenge2,
    challenge3,
    challenge4,
    challenge5,
]

CONGRATS_STR = '所有挑战完成！👏🏻👏🏻👏🏻👏🏻👏🏻👏🏻'
CONGRATS_QUESTION = f'<center><font size=4>{CONGRATS_STR}</center>\n\n <center><font size=3> </center>'

SHARE_CHALLENGES_HINT = [
    '小试牛刀新手上路', '数字玩家已经上线', '巅峰对决，你就是提示词高手', '无人之境，胜利就在前方', '哇塞，我冲出了LLM的重围'
]


def get_problem(challenge_idx, problem_idx):
    problems = challenges[challenge_idx]['problems']
    return problems[problem_idx]


def update_challenge_info(current_chapter_index, current_challenge_index):
    return get_problem(current_chapter_index,
                       current_challenge_index)['description']


def update_question_info(current_chapter_index, current_challenge_index):

    global challenges
    current_chapter = challenges[current_chapter_index]
    challenge = get_problem(current_chapter_index, current_challenge_index)
    question_info = f"""\n<center><font size=4>{current_chapter["name"]}""" \
                    f"""</center>\n\n <center><font size=3>{challenge["title"]}</center>"""
    return question_info


def validate_challenge(response, input, state, generate_response):
    if 'success' in state:
        return CONGRATS_STR, CONGRATS_QUESTION, ''
    assert 'current_chapter_index' in state, 'current_chapter_index not found in state'
    assert 'current_challenge_index' in state, 'current_challenge_index not found in state'
    current_chapter_index = state['current_chapter_index']
    current_challenge_index = state['current_challenge_index']
    # 获取当前章节
    current_chapter = challenges[current_chapter_index]
    # 获取当前挑战
    challenge = current_chapter['problems'][current_challenge_index]

    validate_fn = challenge['validator']
    params = inspect.signature(validate_fn).parameters
    if 'generate_response' in params:
        valid_result = validate_fn(response, input, generate_response)
    else:
        valid_result = validate_fn(response, input)

    if valid_result:
        challenge_result = '挑战成功！进入下一关。'
        # 检查是否还有更多挑战在当前章节
        if current_challenge_index < len(current_chapter['problems']) - 1:
            # 移动到当前章节的下一个挑战
            current_challenge_index += 1
        else:
            # 如果当前章节的挑战已经完成，移动到下一个章节
            if current_chapter_index < len(challenges) - 1:
                current_challenge_index = 0
                current_chapter_index += 1
            else:
                state['success'] = True
                challenge_result = '所有挑战完成！'

    else:
        challenge_result = '挑战失败，请再试一次。'
    state['current_chapter_index'] = current_chapter_index
    state['current_challenge_index'] = current_challenge_index
    print('update state: ', state)
    if 'success' in state:
        return CONGRATS_STR, CONGRATS_QUESTION, ''
    else:
        return challenge_result, \
            update_question_info(current_chapter_index, current_challenge_index), \
            update_challenge_info(current_chapter_index, current_challenge_index)


def generate_response(input, model_name):
    if model_name in model_cache:
        model = model_cache[model_name]
    else:
        model = create_model(model_name)
        model_cache[model_name] = model

    try:
        return model(input)
    except RuntimeError as e:
        # if exception happens, print error in log and return empty str
        print('error', e)
        return ''


def on_submit(input, model_name, state):
    # model_name = os.environ.get('MODEL', 'qwen-plus')
    name_map = {
        'qwen-max': 'qwen-max',
        'qwen-plus': 'qwen-plus',
        'chatglm-turbo': 'chatglm_turbo',
    }
    gen_fn = functools.partial(
        generate_response, model_name=name_map[model_name])
    response = gen_fn(input)
    history = [(input, response)]
    print(history)
    challenge_result, question_info, challenge_info = validate_challenge(
        response, input, state, gen_fn)
    return challenge_result, history, question_info, challenge_info


def generate_share_image(state):
    share_state = state['current_chapter_index']
    if share_state > 3:
        share_state = 3
    if 'success' in state:
        share_state = 4  # 全部通关为 4

    img_pil = Image.open(f'assets/background{share_state}.png')
    # 设置需要显示的字体
    fontpath = 'assets/font.ttf'
    font = ImageFont.truetype(fontpath, 48)
    draw = ImageDraw.Draw(img_pil)
    # 绘制文字信息
    draw.text((70, 1000),
              SHARE_CHALLENGES_HINT[share_state],
              font=font,
              fill=(255, 255, 255))
    if share_state == 4:
        share_chapter_text = '顺利闯过了全部关卡'
    else:
        share_chapter_text = f"我顺利闯到第 {state['current_chapter_index']+1}-{state['current_challenge_index']+1} 关"
    draw.text((70, 1080), share_chapter_text, font=font, fill=(255, 255, 255))
    draw.text((70, 1160), '你也来挑战一下吧～', font=font, fill=(255, 255, 255))

    return gr.Image.update(visible=True, value=img_pil)


def download_resource(url, extract_path='.'):
    """
    下载资源文件，解压到指定路径。

    Args:
      url: 要下载的文件的URL
      extract_path: 解压文件的目标路径
    """
    try:
        # 定义文件名
        filename = url.split('/')[-1]

        # 下载文件
        print(f'Downloading the file from {url}...')
        response = requests.get(url, stream=True)
        if response.status_code == 200:
            with open(filename, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
        else:
            print(
                f'Error: Unable to download file. Status code: {response.status_code}'
            )
            return

        # 解压文件
        print(f'Extracting the file to {extract_path}...')
        if tarfile.is_tarfile(filename):
            with tarfile.open(filename, 'r:*') as tar:
                tar.extractall(path=extract_path)
        else:
            print('Error: The downloaded file is not a tar file.')

        # 删除临时文件
        print(f'Removing the temporary file {filename}...')
        os.remove(filename)
        print(
            'File downloaded, extracted, and temporary file removed successfully.'
        )
    except Exception as e:
        print(f'An error occurred: {e}')


def create_app():
    # Gradio界面构建
    block = gr.Blocks()

    with block as demo:
        current_chapter_index = 0
        current_challenge_index = 0
        state = gr.State(
            dict(
                current_challenge_index=current_challenge_index,
                current_chapter_index=current_chapter_index))

        gr.Markdown("""<center><font size=6>完蛋！我被LLM包围了！</center>""")
        gr.Markdown("""<font size=3>欢迎来玩LLM Riddles复刻版：完蛋！我被LLM包围了！

    你将通过本游戏对大型语言模型产生更深刻的理解。

    在本游戏中，你需要构造一个提给一个大型语言模型的问题，使得它回复的答案符合要求。""")

        model_selector = gr.Dropdown(
            label='选择模型',
            choices=['qwen-max', 'qwen-plus', 'chatglm-turbo'],
            value='qwen-max')
        question_info = gr.Markdown(
            update_question_info(current_chapter_index,
                                 current_challenge_index))
        challenge_info = gr.Textbox(
            value=update_challenge_info(current_chapter_index,
                                        current_challenge_index),
            label='当前挑战',
            interactive=False)
        challenge_result = gr.Textbox(label='挑战结果', interactive=False)
        chatbot = gr.Chatbot(label='llm', elem_classes='control-height')
        message = gr.Textbox(lines=2, label='输入')

        with gr.Row():
            submit = gr.Button('🚀 发送')
            shareBtn = gr.Button('💯 分享成绩')

        shareImg = gr.Image(label='分享成绩', visible=False, width=400)

        submit.click(
            on_submit,
            inputs=[message, model_selector, state],
            outputs=[challenge_result, chatbot, question_info, challenge_info])
        shareBtn.click(
            generate_share_image, inputs=[state], outputs=[shareImg])

        gr.HTML("""
    <div style="text-align: center;">
      <span>
        Powered by <a href="https://dashscope.aliyun.com/" target="_blank">
        <img src=
        "//img.alicdn.com/imgextra/i4/O1CN01SgKFXM1qLQwFvk6j5_!!6000000005479-2-tps-99-84.png"
        style="display: inline; height: 20px; vertical-align: bottom;"/>DashScope
        </a>
      </span>
    </div>
    """)

    demo.queue(concurrency_count=10).launch(height=800, share=True)


if __name__ == '__main__':
    if not os.path.exists('assets'):
        download_resource(
            'https://modelscope.oss-cn-beijing.aliyuncs.com/resource/llm_riddles_assets.tar'
        )
    create_app()
