"""
md文件优化
"""

import os
import time


# 移除md文件中多余空行
def remove_more_empty_line(path):
    new_lines = []
    with open(path, 'r') as file:
        lines = file.readlines()
        pre_line_empty = False
        for line in lines:
            if pre_line_empty and line == '\n':
                continue
            pre_line_empty = (line == '\n')
            new_lines.append(line)
        if len(lines) == len(new_lines):
            return
    print('文件有多余空行，已移除', path)
    with open(path, 'w') as file:
        file.writelines(new_lines)


# 添加hexo文件头信息
def add_hexo_title(path):
    with open(path, 'r') as file:
        lines = file.readlines()
        if lines[0].startswith('---') and lines[1].startswith('layout'):
            return
    print('文件没有hexo信息，已添加', path)
    with open(path, 'w') as file:
        title = os.path.basename(file.name)
        categories = os.path.basename(os.path.dirname(file.name))
        hexo_title = ('---\nlayout: blog\ntitle: {}\ndate: {}\n'
                      'categories: [{}]\ntags: []\ntoc: true\ncomments: true\n---\n\n').format(
            title[:title.index('.')], time.strftime("%Y-%m-%d %H:%M:%S"), categories)
        lines.insert(0, hexo_title)
        file.writelines(lines)


# 更新md文件中的图片地址
def update_img_path(path):
    new_lines = []
    with open(path, 'r') as file:
        lines = file.readlines()
        if not [v for v in lines if '<img src=' in v]:
            return
        for line in lines:
            if '<img src=' in line:
                new_lines.append('![](' + line[12:-4] + ')')
            else:
                new_lines.append(line)
    print('文件有待更新图片地址，已更新', path)
    with open(path, 'w') as file:
        file.writelines(new_lines)


# 移除md文件中不存在的图片
def remove_more_img(path):
    with open(path, 'r') as file:
        lines = str([v.strip()[v.index('(') + 1:-1] for v in file.readlines() if '_image' in v])
        title = os.path.basename(file.name)
        images_dir = os.path.dirname(file.name) + '/_image/' + title[:title.index('.')]
        if not os.path.exists(images_dir):
            return
        images = [v for v in os.listdir(images_dir) if v != '.DS_Store']
        for v in images:
            if v in lines:
                continue
            # 删除该文件
            print('删除多余文件', os.path.join(images_dir, v))
            os.remove(os.path.join(images_dir, v))


if __name__ == '__main__':
    base_dirs = ['操作系统', '框架研究', 'Java', 'MySQL', '分布式系统', '随笔']
    for base in base_dirs:
        for root, dirs, files in os.walk(base):
            files = [v for v in files if v.endswith('.md')]
            if not files:
                continue
            for v in files:
                f = os.path.join(root, v)
                add_hexo_title(f)
                remove_more_empty_line(f)
                remove_more_img(f)
