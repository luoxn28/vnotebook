import os
import shutil

# 复制md文件
from stripmd import remove_more_empty_line, remove_more_img, add_hexo_title, update_img_path


def build_hexo_md(path, dest_dir):
    with open(path, 'r') as file:
        lines = file.readlines()
        for i, v in enumerate(lines):
            if '_image' not in v:
                continue
            lines[i] = v.replace('_image', '.')

        # 存在则比较是否相同
        dest_file = os.path.join(dest_dir, os.path.basename(file.name))
        if os.path.exists(dest_file):
            with open(dest_file, 'r') as f:
                if lines == f.readlines():
                    return

        # 文件不存在或者有更新直接写入
        with open(dest_file, 'w') as f:
            f.writelines(lines)
            print('md文件不存在或有更新，已写入', dest_file)


def build_hexo_image(path, dest_dir):
    dir = os.path.dirname(path)
    name = os.path.basename(path)[:os.path.basename(path).index('.')]
    if not os.path.exists(os.path.join(dir, '_image')) \
            or not os.path.exists(os.path.join(dir, '_image/' + name)):
        return
    old_dir = os.path.join(dir, '_image/' + name)
    images = [v for v in os.listdir(old_dir) if v != '.DS_Store']

    if not os.path.exists(os.path.join(dest_dir, name)):
        os.mkdir(os.path.join(dest_dir, name))
    new_dir = os.path.join(dest_dir, name + '/' + name)
    if not os.path.exists(new_dir):
        os.mkdir(new_dir)
    # 多余的文件删除
    for v in [os.path.join(new_dir, v) for v in os.listdir(new_dir) if v not in images]:
        print('删除hexo多余文件', v)
        os.remove(v)
    for v in [v for v in images if v not in os.listdir(new_dir)]:
        print('复制文件到hexo', os.path.join(new_dir, v))
        shutil.copy(os.path.join(old_dir, v), new_dir)


if __name__ == '__main__':
    dest = '/Users/luoxiangnan/luoxn28/source/_posts'
    base_dirs = ['操作系统', '框架研究', 'Java', '数据库', '分布式', '随笔']
    for base in base_dirs:
        for root, dirs, files in os.walk(base):
            files = [v for v in files if v.endswith('.md')]
            if not files:
                continue
            for v in files:
                f = os.path.join(root, v)
                add_hexo_title(f)
                remove_more_empty_line(f)
                # update_img_path(f)
                remove_more_img(f)
                build_hexo_md(f, dest)
                build_hexo_image(f, dest)
