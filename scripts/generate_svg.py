import os
import re
import json
import requests
from collections import defaultdict
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime

# --- 配置区 ---
# 从环境变量获取配置
GITHUB_TOKEN = os.environ.get('GH_TOKEN')
REPO_NAME = os.environ.get('REPO_NAME') # 格式: username/repo
ISSUE_NUMBER = os.environ.get('ISSUE_NUMBER')
OUTPUT_FILE = 'assets/claude_usage.svg'

# 配色方案 (参考 Claude 风格或 GitHub 风格)
COLORS = {
    'Input': '#7c7cff',       # 蓝色系
    'Output': '#51cf66',      # 绿色系
    'Cache Read': '#fcc419',  # 黄色系 (高亮显示的节省量)
    'Cache Write': '#ff922b'  # 橙色系
}

# --- 函数定义 ---

def fetch_issue_comments():
    """获取指定 Issue 的所有评论"""
    url = f"https://api.github.com/repos/{REPO_NAME}/issues/{ISSUE_NUMBER}/comments?per_page=100"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    comments = []
    while url:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        data = response.json()
        comments.extend(data)
        # 处理分页
        url = response.links.get('next', {}).get('url')
    return comments

def extract_and_aggregate_data(comments):
    """
    解析评论中的 JSON 元数据并按日期聚合。
    聚合逻辑：按 target_date 分组，累加该日所有终端的所有模型的不同类型 token。
    """
    # 用于存储聚合数据的字典: aggregated_data[date][token_type] = total_count
    aggregated_data = defaultdict(lambda: defaultdict(int))
    
    # 正则表达式匹配隐藏块
    regex = r""
    
    print(f"找到 {len(comments)} 条评论，开始解析...")
    
    for comment in comments:
        match = re.search(regex, comment['body'], re.DOTALL)
        if match:
            try:
                json_str = match.group(1)
                data = json.loads(json_str)
                
                target_date = data.get('target_date')
                stats = data.get('stats', [])
                
                if not target_date or not stats:
                    continue

                # 累加当天各个模型的数据
                for model_stat in stats:
                    aggregated_data[target_date]['Input'] += model_stat.get('input', 0)
                    aggregated_data[target_date]['Output'] += model_stat.get('output', 0)
                    aggregated_data[target_date]['Cache Read'] += model_stat.get('cache_read', 0)
                    aggregated_data[target_date]['Cache Write'] += model_stat.get('cache_write', 0)
                    
            except json.JSONDecodeError:
                print(f"警告: 无法解析评论 ID {comment['id']} 中的 JSON。")
                continue

    return aggregated_data

def generate_chart(aggregated_data):
    """生成堆叠柱状图 SVG"""
    if not aggregated_data:
        print("没有数据，跳过绘图。")
        return

    # 1. 准备绘图数据
    sorted_dates = sorted(aggregated_data.keys())
    # 只取最近 14 天的数据，避免图表过长
    display_dates = sorted_dates[-14:] 
    
    dates_for_plot = [datetime.strptime(d, '%Y-%m-%d').date() for d in display_dates]
    
    token_types = ['Input', 'Cache Write', 'Cache Read', 'Output'] # 堆叠顺序，Output 在最上面
    
    plot_data = {T: [] for T in token_types}
    for d in display_dates:
        daily_stats = aggregated_data[d]
        for T in token_types:
            plot_data[T].append(daily_stats.get(T, 0))

    # 2. 配置 Matplotlib
    # 设置适合 GitHub 的深色背景风格，但最后会设为透明
    plt.style.use('dark_background') 
    fig, ax = plt.subplots(figsize=(10, 5)) # 宽长图
    fig.patch.set_facecolor('none') # 图片背景透明
    ax.set_facecolor('none')        # 坐标轴背景透明

    # 3. 绘制堆叠柱状图
    bottom = [0] * len(display_dates)
    bars = []
    for T in token_types:
        bar = ax.bar(dates_for_plot, plot_data[T], bottom=bottom, label=T, color=COLORS[T], edgecolor='none', alpha=0.9)
        bars.append(bar)
        # 更新下一层的底部位置
        bottom = [b + v for b, v in zip(bottom, plot_data[T])]

    # 4. 设置图表样式
    ax.set_title('Claude Code Daily Token Usage (Last 14 Days)', color='#c9d1d9', fontsize=14, pad=20)
    
    # X 轴日期格式化
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d'))
    ax.xaxis.set_major_locator(mdates.DayLocator(interval=1))
    plt.xticks(rotation=45, color='#8b949e')
    
    # Y 轴设置
    ax.yaxis.set_tick_params(colors='#8b949e')
    # 使用 FuncFormatter 将 Y 轴标签转换为 K/M 单位 (例如 15000 -> 15K)
    def k_formatter(x, pos):
        if x >= 1000000:
            return f'{x*1e-6:.1f}M'
        elif x >= 1000:
            return f'{x*1e-3:.0f}K'
        return f'{x:.0f}'
    ax.yaxis.set_major_formatter(plt.FuncFormatter(k_formatter))

    # 移除多余的边框线，只保留底部的
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['left'].set_visible(False)
    ax.spines['bottom'].set_color('#30363d')
    
    # 添加横向网格线辅助阅读
    ax.grid(axis='y', linestyle='--', alpha=0.3, color='#30363d')

    # 图例设置
    legend = ax.legend(loc='upper left', frameon=False, fontsize=10)
    for text in legend.get_texts():
        text.set_color('#c9d1d9')

    # 5. 保存文件
    # 确保输出目录存在
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    plt.tight_layout()
    plt.savefig(OUTPUT_FILE, format='svg', transparent=True, bbox_inches='tight')
    print(f"SVG 图表已生成至: {OUTPUT_FILE}")
    plt.close()

# --- 主程序 ---
if __name__ == "__main__":
    if not all([GITHUB_TOKEN, REPO_NAME, ISSUE_NUMBER]):
        print("错误: 缺少必要的环境变量 (GH_TOKEN, REPO_NAME, ISSUE_NUMBER)")
        exit(1)
        
    comments = fetch_issue_comments()
    aggregated_data = extract_and_aggregate_data(comments)
    generate_chart(aggregated_data)