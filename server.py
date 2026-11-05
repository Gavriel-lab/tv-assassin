"""
电视刺客 🗡️📺 (TV-Assassin) v1.0
开发者 / 维护者: 林深 (老林 / Lin Shen)
开源协议: CC BY-NC 4.0 (知识共享署名-非商业性使用 4.0 国际许可协议)
严正声明: 本项目仅供家庭非商业性学习与育儿交流使用，严禁任何形式的商业售卖、硬件捆绑或广告植入！
"""

import datetime
import json
import os
import random
import socket
import subprocess
import sys
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
STATE_FILE = os.path.join(BASE_DIR, "tv_state.json")
QUESTIONS_FILE = os.path.join(BASE_DIR, "questions.json")
MISTAKES_FILE = os.path.join(BASE_DIR, "mistakes.json")

# 自动寻找 ADB 路径（优先内置便携版，其次系统 PATH）
def find_adb():
    local_adb = os.path.join(BASE_DIR, "tools", "adb", "adb.exe")
    if os.path.exists(local_adb):
        return local_adb
    in_dir_adb = os.path.join(BASE_DIR, "adb.exe")
    if os.path.exists(in_dir_adb):
        return in_dir_adb
    return "adb"

ADB_PATH = find_adb()

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

LOCAL_IP = get_local_ip()

class ConfigManager:
    def __init__(self):
        self.lock = threading.Lock()
        self.data = {
            "tv_ip": "",
            "tv_port": 5555,
            "server_port": 3000,
            "max_earned_minutes": 30,
            "minutes_per_correct": 10
        }
        self.load()

    def load(self):
        with self.lock:
            if os.path.exists(CONFIG_FILE):
                try:
                    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                        self.data.update(json.load(f))
                except Exception as e:
                    print(f"[Config] 读取配置失败: {e}")

    def save(self):
        with self.lock:
            try:
                with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                    json.dump(self.data, f, ensure_ascii=False, indent=2)
            except Exception as e:
                print(f"[Config] 保存配置失败: {e}")

    def get(self, key, default=None):
        with self.lock:
            return self.data.get(key, default)

    def set_many(self, kv_dict):
        with self.lock:
            self.data.update(kv_dict)
        self.save()

config = ConfigManager()

class DataManager:
    def __init__(self):
        self.lock = threading.Lock()

    def get_questions(self):
        with self.lock:
            if os.path.exists(QUESTIONS_FILE):
                try:
                    with open(QUESTIONS_FILE, "r", encoding="utf-8") as f:
                        return json.load(f)
                except Exception:
                    pass
            return []

    def save_questions(self, qs):
        with self.lock:
            try:
                with open(QUESTIONS_FILE, "w", encoding="utf-8") as f:
                    json.dump(qs, f, ensure_ascii=False, indent=2)
            except Exception as e:
                print(f"[Data] 保存题库失败: {e}")

    def add_question(self, q):
        qs = self.get_questions()
        q["id"] = max([item.get("id", 0) for item in qs] + [0]) + 1
        qs.append(q)
        self.save_questions(qs)
        return q

    def get_random_question(self):
        qs = self.get_questions()
        if not qs:
            return None
        return random.choice(qs)

    def get_mistakes(self):
        with self.lock:
            if os.path.exists(MISTAKES_FILE):
                try:
                    with open(MISTAKES_FILE, "r", encoding="utf-8") as f:
                        return json.load(f)
                except Exception:
                    pass
            return []

    def record_mistake(self, q, selected_idx):
        with self.lock:
            mistakes = []
            if os.path.exists(MISTAKES_FILE):
                try:
                    with open(MISTAKES_FILE, "r", encoding="utf-8") as f:
                        mistakes = json.load(f)
                except Exception:
                    pass
            
            selected_text = q["options"][selected_idx] if 0 <= selected_idx < len(q["options"]) else "未知"
            correct_text = q["options"][q["answer"]] if 0 <= q["answer"] < len(q["options"]) else "未知"

            rec = {
                "id": int(time.time() * 1000),
                "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "subject": q.get("subject", "other"),
                "subject_label": q.get("subject_label", "通用"),
                "question": q.get("question", ""),
                "selected_option": selected_text,
                "correct_option": correct_text,
                "hint": q.get("hint", "")
            }
            mistakes.insert(0, rec)
            try:
                with open(MISTAKES_FILE, "w", encoding="utf-8") as f:
                    json.dump(mistakes, f, ensure_ascii=False, indent=2)
            except Exception as e:
                print(f"[Data] 记录错题失败: {e}")

    def clear_mistakes(self):
        with self.lock:
            try:
                with open(MISTAKES_FILE, "w", encoding="utf-8") as f:
                    json.dump([], f, ensure_ascii=False, indent=2)
            except Exception:
                pass

db = DataManager()

class TVState:
    def __init__(self):
        self.lock = threading.Lock()
        self.mode = "quiz" # "quiz" (答题充值模式) 或 "manual" (家长掌权模式)
        self.is_locked = True
        self.remaining_seconds = 0
        self.timer_active = False
        self.earned_minutes = 0
        self.message = "时间到了，该写作业了！"
        self.tv_online = False
        self.load()

    def load(self):
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.mode = data.get("mode", "quiz")
                    self.is_locked = data.get("is_locked", True)
                    self.message = data.get("message", "时间到了，该写作业了！")
                    self.remaining_seconds = data.get("remaining_seconds", 0)
                    self.timer_active = data.get("timer_active", False)
                    self.earned_minutes = data.get("earned_minutes", 0)
            except Exception as e:
                print(f"[State] 读取状态失败: {e}")

    def save(self):
        try:
            with open(STATE_FILE, "w", encoding="utf-8") as f:
                json.dump({
                    "mode": self.mode,
                    "is_locked": self.is_locked,
                    "message": self.message,
                    "remaining_seconds": self.remaining_seconds,
                    "timer_active": self.timer_active,
                    "earned_minutes": self.earned_minutes
                }, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[State] 写入状态失败: {e}")

state = TVState()

def run_adb(cmd, timeout=5):
    tv_ip = config.get("tv_ip")
    tv_port = config.get("tv_port", 5555)
    if not tv_ip:
        return False, "TV IP not set"

    full_cmd = f'"{ADB_PATH}" -s {tv_ip}:{tv_port} {cmd}'
    try:
        res = subprocess.run(full_cmd, shell=True, capture_output=True, timeout=timeout)
        raw = res.stdout or b""
        try:
            out_str = raw.decode('utf-8')
        except UnicodeDecodeError:
            out_str = raw.decode('gbk', errors='ignore')
        return res.returncode == 0, out_str.strip()
    except Exception as e:
        return False, str(e)

def ensure_adb_connected():
    tv_ip = config.get("tv_ip")
    tv_port = config.get("tv_port", 5555)
    if not tv_ip:
        with state.lock:
            state.tv_online = False
        return False

    full_cmd = f'"{ADB_PATH}" connect {tv_ip}:{tv_port}'
    try:
        res = subprocess.run(full_cmd, shell=True, capture_output=True, timeout=4)
        raw = res.stdout or b""
        try:
            output = raw.decode('utf-8')
        except UnicodeDecodeError:
            output = raw.decode('gbk', errors='ignore')
        is_conn = "connected" in output or "already" in output
        with state.lock:
            state.tv_online = is_conn
        return is_conn
    except Exception:
        with state.lock:
            state.tv_online = False
        return False

def show_lock_screen_on_tv():
    server_port = config.get("server_port", 3000)
    url = f"http://{LOCAL_IP}:{server_port}/tv-lock"
    run_adb(f'shell am start -a android.intent.action.VIEW -d "{url}"')
    run_adb('shell input keyevent 164') # 静音

def unlock_tv():
    run_adb('shell input keyevent 3') # 按主页键
    run_adb('shell media volume --set 10')

def guardian_loop():
    print(f"[Guardian] 电视守护线程启动...")
    last_adb_connect_time = 0
    
    while True:
        try:
            now = time.time()
            if now - last_adb_connect_time > 8:
                ensure_adb_connected()
                last_adb_connect_time = now

            with state.lock:
                timer_active = state.timer_active
                is_locked = state.is_locked

                if timer_active and state.remaining_seconds > 0:
                    state.remaining_seconds -= 1
                    if state.remaining_seconds <= 0:
                        state.timer_active = False
                        state.is_locked = True
                        state.earned_minutes = 0
                        is_locked = True
                        print("[Guardian] 倒计时结束，自动锁屏并回归答题！")
                    state.save()

            if is_locked and state.tv_online:
                ok, focus = run_adb("shell \"dumpsys activity activities | grep -E 'mResumedActivity'\"")
                if ok:
                    if "browser" not in focus and "Browser" not in focus:
                        show_lock_screen_on_tv()

            time.sleep(1)
        except Exception as e:
            time.sleep(2)

INDEX_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
  <title>电视刺客 · 专刺偷看电视神兽</title>
  <style>
    :root {
      --primary: #4f46e5;
      --primary-hover: #4338ca;
      --danger: #ef4444;
      --success: #10b981;
      --warning: #f59e0b;
      --bg: #0b1120;
      --card: #1e293b;
      --border: #334155;
      --text: #f8fafc;
      --muted: #94a3b8;
    }
    * { margin:0; padding:0; box-sizing: border-box; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Microsoft YaHei", sans-serif; }
    body { background-color: var(--bg); color: var(--text); padding: 14px; min-height: 100vh; }
    .container { max-width: 680px; margin: 0 auto; display: flex; flex-direction: column; gap: 14px; }
    
    .header { display: flex; justify-content: space-between; align-items: center; padding: 12px 16px; background: var(--card); border-radius: 16px; border: 1px solid var(--border); }
    .header h1 { font-size: 17px; font-weight: 700; display: flex; align-items: center; gap: 8px; }
    .status-badge { display: inline-flex; align-items: center; gap: 6px; padding: 4px 10px; border-radius: 20px; font-size: 12px; font-weight: 600; background: rgba(16, 185, 129, 0.15); color: var(--success); }
    .status-badge.offline { background: rgba(239, 68, 68, 0.15); color: var(--danger); }
    .status-dot { width: 8px; height: 8px; border-radius: 50%; background: currentColor; }

    /* 首次配置引导弹窗/卡片 */
    .setup-banner { background: linear-gradient(135deg, rgba(79, 70, 229, 0.15), rgba(16, 185, 129, 0.15)); border: 2px dashed var(--primary); border-radius: 16px; padding: 20px; display: none; flex-direction: column; gap: 12px; }
    .setup-banner h2 { font-size: 16px; color: #a5b4fc; }

    /* 模式切换栏 */
    .mode-bar { display: grid; grid-template-columns: 1fr 1fr; background: #0f172a; padding: 4px; border-radius: 14px; border: 1px solid var(--border); gap: 6px; }
    .mode-btn { border: none; padding: 10px 0; border-radius: 10px; font-size: 14px; font-weight: 700; cursor: pointer; color: var(--muted); background: transparent; transition: all 0.2s; }
    .mode-btn.active { background: var(--primary); color: white; box-shadow: 0 4px 12px rgba(79, 70, 229, 0.35); }

    .nav-tabs { display: flex; gap: 8px; border-bottom: 1px solid var(--border); padding-bottom: 8px; }
    .nav-tab { padding: 6px 14px; border-radius: 8px; font-size: 13px; font-weight: 600; cursor: pointer; color: var(--muted); background: transparent; border: none; }
    .nav-tab.active { background: var(--border); color: white; }

    .card { background: var(--card); border-radius: 16px; padding: 18px; border: 1px solid var(--border); display: flex; flex-direction: column; gap: 14px; }
    .card-title { font-size: 14px; font-weight: 600; color: var(--muted); display: flex; align-items: center; justify-content: space-between; }

    .state-banner { text-align: center; padding: 16px; border-radius: 14px; background: rgba(255,255,255,0.03); border: 1px dashed var(--border); }
    .state-banner.locked { background: rgba(239, 68, 68, 0.1); border-color: var(--danger); }
    .state-title { font-size: 12px; color: var(--muted); margin-bottom: 4px; }
    .countdown { font-size: 38px; font-weight: 800; font-variant-numeric: tabular-nums; }
    .state-banner.locked .countdown { color: var(--danger); }
    .state-banner.running .countdown { color: #38bdf8; }

    .timer-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; }
    .time-btn { background: #334155; border: none; color: var(--text); padding: 10px 0; border-radius: 10px; font-size: 14px; font-weight: 600; cursor: pointer; }
    .time-btn:active { background: var(--primary); }

    .action-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
    .btn { border: none; border-radius: 12px; padding: 12px; font-size: 15px; font-weight: 700; cursor: pointer; display: flex; align-items: center; justify-content: center; gap: 6px; }
    .btn:active { transform: scale(0.97); }
    .btn-lock { background: var(--danger); color: white; }
    .btn-unlock { background: var(--success); color: white; }
    .btn-add { background: #0284c7; color: white; }
    .btn-sleep { background: #475569; color: white; }

    .presets { display: flex; flex-wrap: wrap; gap: 6px; }
    .preset-pill { background: rgba(255,255,255,0.06); border: 1px solid var(--border); padding: 5px 10px; border-radius: 20px; font-size: 12px; color: #cbd5e1; cursor: pointer; }

    textarea, input[type="text"] { width: 100%; background: #0f172a; border: 1px solid var(--border); border-radius: 10px; padding: 10px; color: white; font-size: 13px; outline: none; }
    textarea { height: 60px; resize: none; }

    .mistake-list { display: flex; flex-direction: column; gap: 10px; max-height: 480px; overflow-y: auto; }
    .mistake-item { background: #0f172a; border-radius: 12px; padding: 14px; border-left: 4px solid var(--danger); border-top: 1px solid var(--border); border-right: 1px solid var(--border); border-bottom: 1px solid var(--border); display: flex; flex-direction: column; gap: 6px; }
    .mistake-header { display: flex; justify-content: space-between; align-items: center; font-size: 12px; }
    .tag { padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; }
    .tag-math { background: #1e3a8a; color: #93c5fd; }
    .tag-chinese { background: #831843; color: #fbcfe8; }
    .tag-english { background: #064e3b; color: #6ee7b7; }
    .mistake-q { font-size: 14px; font-weight: 600; line-height: 1.4; color: #f1f5f9; }
    .mistake-answers { display: flex; flex-direction: column; gap: 3px; font-size: 13px; margin-top: 4px; }
    .ans-wrong { color: #f87171; }
    .ans-right { color: #4ade80; }
    .mistake-hint { font-size: 12px; color: #94a3b8; background: rgba(255,255,255,0.03); padding: 6px 8px; border-radius: 6px; margin-top: 4px; }

    .filter-bar { display: flex; gap: 6px; }
    .filter-btn { padding: 4px 10px; border-radius: 6px; font-size: 12px; background: #1e293b; border: 1px solid var(--border); color: var(--muted); cursor: pointer; }
    .filter-btn.active { background: var(--primary); color: white; border-color: var(--primary); }

    .screenshot-box { border-radius: 10px; overflow: hidden; background: #000; border: 1px solid var(--border); min-height: 140px; display: flex; justify-content: center; align-items: center; }
    .screenshot-box img { width: 100%; display: block; object-fit: contain; }
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>🗡️ 电视刺客 · TV-Assassin</h1>
      <div id="statusBadge" class="status-badge"><span class="status-dot"></span><span id="statusText">连接中...</span></div>
    </div>

    <!-- 首次连接配置栏 -->
    <div id="setupBanner" class="setup-banner">
      <h2>👋 欢迎！请先连接您家客厅的电视：</h2>
      <div style="font-size:13px; color:#cbd5e1; line-height:1.5;">
        请在电视设置中开启 <b>ADB/USB调试</b>，并在网络设置中查看电视的局域网 IP（需与本设备连接同一 WiFi）：
      </div>
      <div style="display:flex; gap:8px;">
        <input type="text" id="inputTvIp" placeholder="例如: 192.168.1.105">
        <button class="btn btn-unlock" style="white-space:nowrap; padding:0 20px;" onclick="saveTvIp()">保存并连接</button>
      </div>
      <div style="font-size:12px; color:var(--muted);">
        💡 提示：保存后电视屏幕通常会弹出“允许来自此计算机的调试？”，拿遥控器勾选“一律允许”并点击确定即可！
      </div>
    </div>

    <!-- 顶层模式切换器 -->
    <div class="mode-bar">
      <button id="btnModeQuiz" class="mode-btn active" onclick="switchMode('quiz')">🎮 答题充值模式 (全自动)</button>
      <button id="btnModeManual" class="mode-btn" onclick="switchMode('manual')">⏱️ 家长掌权模式 (手动遥控)</button>
    </div>

    <!-- 导航标签 -->
    <div class="nav-tabs">
      <button class="nav-tab active" onclick="switchTab('control')">🎛️ 运行控制</button>
      <button class="nav-tab" onclick="switchTab('mistakes')">📝 孩子错题本 (<span id="mistakeCount">0</span>)</button>
      <button class="nav-tab" onclick="switchTab('questions')">📚 题库概览</button>
      <button class="nav-tab" onclick="switchTab('settings')">⚙️ 设置</button>
    </div>

    <!-- 控制页 -->
    <div id="tab-control" style="display:flex; flex-direction:column; gap:14px;">
      <div class="card">
        <div class="card-title">
          <span>⏱️ 当前状态</span>
          <span id="modeDesc" style="font-size:12px; color:var(--primary); font-weight:700;">【答题充值模式】</span>
        </div>
        <div id="stateBanner" class="state-banner">
          <div id="stateTitle" class="state-title">未开启定时</div>
          <div id="countdown" class="countdown">00:00</div>
          <div id="quizProgress" style="font-size:13px; color:#f59e0b; margin-top:4px; font-weight:600;">已答题积攒：0 / 30 分钟</div>
        </div>
        
        <div class="action-grid" style="margin-top:4px;">
          <button class="btn btn-lock" onclick="triggerLock()">🚨 立即锁屏</button>
          <button class="btn btn-unlock" onclick="triggerUnlock()">🔓 一键解锁</button>
          <button class="btn btn-add" onclick="addTime(10)">➕ 奖励 10 分钟</button>
          <button class="btn btn-sleep" onclick="triggerSleep()">😴 息屏待机</button>
        </div>

        <div id="manualControls" style="display:none; flex-direction:column; gap:10px; margin-top:8px; border-top:1px solid var(--border); padding-top:12px;">
          <div class="card-title">⚡ 手动快速设定看电视时长</div>
          <div class="timer-grid">
            <button class="time-btn" onclick="setTimer(15)">15分</button>
            <button class="time-btn" onclick="setTimer(30)">30分</button>
            <button class="time-btn" onclick="setTimer(45)">45分</button>
            <button class="time-btn" onclick="setTimer(60)">60分</button>
          </div>
        </div>
      </div>

      <div class="card">
        <div class="card-title">📢 电视屏幕留言 (大屏广播)</div>
        <textarea id="msgInput" placeholder="输入大屏显示的文字...">时间到了，该写作业了！</textarea>
        <div class="presets">
          <span class="preset-pill" onclick="setMsg('时间到了，该写作业了！')">📝 时间到了写作业</span>
          <span class="preset-pill" onclick="setMsg('哥哥时间到了，把遥控器给弟弟！')">🎮 轮到弟弟看了</span>
          <span class="preset-pill" onclick="setMsg('弟弟时间到了，把遥控器给哥哥！')">🎮 轮到哥哥看了</span>
          <span class="preset-pill" onclick="setMsg('菜就多练，再做两题！')">😏 菜就多练</span>
        </div>
      </div>

      <div class="card">
        <div class="card-title">
          <span>👀 电视实时截屏 (偷瞄)</span>
          <button class="filter-btn" onclick="refreshScreenshot()">🔄 刷新截屏</button>
        </div>
        <div class="screenshot-box">
          <img id="screenImg" src="/api/screenshot" alt="电视实时截屏">
        </div>
      </div>
    </div>

    <!-- 错题本页 -->
    <div id="tab-mistakes" style="display:none; flex-direction:column; gap:14px;">
      <div class="card">
        <div class="card-title">
          <span>📝 薄弱点错题自动收集</span>
          <button class="filter-btn" style="color:var(--danger);" onclick="clearMistakes()">🗑️ 清空记录</button>
        </div>
        <div class="filter-bar">
          <button class="filter-btn active" onclick="filterMistakes('all', this)">全部</button>
          <button class="filter-btn" onclick="filterMistakes('math', this)">📐 数学</button>
          <button class="filter-btn" onclick="filterMistakes('chinese', this)">📖 语文</button>
          <button class="filter-btn" onclick="filterMistakes('english', this)">🔤 英语</button>
        </div>
        <div id="mistakeList" class="mistake-list">
          <div style="text-align:center; padding:30px; color:var(--muted); font-size:13px;">暂无错题，表现很棒！🎉</div>
        </div>
      </div>
    </div>

    <!-- 题库概览页 -->
    <div id="tab-questions" style="display:none; flex-direction:column; gap:14px;">
      <div class="card">
        <div class="card-title">
          <span>📚 当前题库列表</span>
          <span id="totalQuestions" style="font-size:12px;">共 0 题</span>
        </div>
        <div style="font-size:13px; color:var(--muted); line-height:1.5;">
          题目支持在 questions.json 中自由扩充，亦可在下面直接预览。答题模式将从题库中随机抽取并记录错题。
        </div>
        <div id="questionsList" class="mistake-list" style="max-height:400px;"></div>
      </div>
    </div>

    <!-- 设置页 -->
    <div id="tab-settings" style="display:none; flex-direction:column; gap:14px;">
      <div class="card">
        <div class="card-title">⚙️ 系统网络与电视配置</div>
        <div style="display:flex; flex-direction:column; gap:8px;">
          <label style="font-size:13px; color:var(--muted);">电视 IP 地址 (局域网)</label>
          <input type="text" id="settingsTvIp" placeholder="例如 192.168.1.100">
          <button class="btn btn-unlock" style="margin-top:4px;" onclick="saveSettings()">💾 保存配置并测试连接</button>
        </div>
        <div style="font-size:12px; color:var(--muted); line-height:1.6; margin-top:10px;">
          <b>常见电视品牌开启 ADB 调试方法：</b><br>
          • <b>TCL / 雷鸟</b>：设置 -> 关于本机 -> 本机信息 -> 遥控器按“上、下、左、右”开启。<br>
          • <b>小米电视</b>：设置 -> 关于 -> 产品型号连续按确定键 7 次，返回账号与安全开启 ADB。<br>
          • <b>索尼电视</b>：设置 -> 开发者选项 -> USB调试开启。<br>
          • <b>华为智慧屏</b>：关于 -> 版本号连按 7 次打开开发者选项。
        </div>
      </div>
    </div>

    <!-- 底部创作者与开源版权声明 -->
    <div style="text-align:center; padding:16px 0 8px 0; font-size:12px; color:var(--muted); line-height:1.6; border-top:1px dashed var(--border); margin-top:8px;">
      🗡️ <b>电视刺客 (TV-Assassin)</b> · 开发者: 林深 (老林)<br>
      基于 <a href="https://creativecommons.org/licenses/by-nc/4.0/deed.zh-hans" target="_blank" style="color:#a5b4fc; text-decoration:none;">CC BY-NC 4.0</a> 协议开源 · 仅供家庭非商业使用 · 严禁商售倒卖
    </div>

  </div>

  <script>
    let currentTab = 'control';
    let allMistakes = [];
    let currentFilter = 'all';

    function setMsg(txt) {
      document.getElementById('msgInput').value = txt;
    }

    function switchTab(tab) {
      currentTab = tab;
      document.querySelectorAll('.nav-tab').forEach((el, idx) => {
        el.classList.toggle('active', (tab === 'control' && idx === 0) || (tab === 'mistakes' && idx === 1) || (tab === 'questions' && idx === 2) || (tab === 'settings' && idx === 3));
      });
      document.getElementById('tab-control').style.display = tab === 'control' ? 'flex' : 'none';
      document.getElementById('tab-mistakes').style.display = tab === 'mistakes' ? 'flex' : 'none';
      document.getElementById('tab-questions').style.display = tab === 'questions' ? 'flex' : 'none';
      document.getElementById('tab-settings').style.display = tab === 'settings' ? 'flex' : 'none';
      if (tab === 'mistakes') loadMistakes();
      if (tab === 'questions') loadQuestions();
    }

    async function apiPost(url, data = {}) {
      try {
        const res = await fetch(url, {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify(data)
        });
        return await res.json();
      } catch (e) {
        alert('操作失败，请检查网络');
      }
    }

    async function switchMode(m) {
      await apiPost('/api/mode', { mode: m });
      pollStatus();
    }

    function setTimer(minutes) {
      const msg = document.getElementById('msgInput').value.trim();
      apiPost('/api/timer', { minutes, message: msg });
    }

    function triggerLock() {
      const msg = document.getElementById('msgInput').value.trim();
      apiPost('/api/lock', { message: msg });
    }

    function triggerUnlock() {
      apiPost('/api/unlock');
    }

    function triggerSleep() {
      apiPost('/api/sleep');
    }

    function addTime(minutes) {
      apiPost('/api/add_time', { minutes });
    }

    function refreshScreenshot() {
      const img = document.getElementById('screenImg');
      img.src = '/api/screenshot?t=' + Date.now();
    }

    async function saveTvIp() {
      const ip = document.getElementById('inputTvIp').value.trim();
      if (!ip) return alert('请输入有效的 IP 地址');
      await apiPost('/api/config', { tv_ip: ip });
      document.getElementById('setupBanner').style.display = 'none';
      pollStatus();
    }

    async function saveSettings() {
      const ip = document.getElementById('settingsTvIp').value.trim();
      if (!ip) return alert('请输入有效的 IP 地址');
      await apiPost('/api/config', { tv_ip: ip });
      alert('配置已保存！正在尝试连接电视...');
      pollStatus();
    }

    async function loadMistakes() {
      try {
        const res = await fetch('/api/mistakes');
        allMistakes = await res.json();
        document.getElementById('mistakeCount').innerText = allMistakes.length;
        renderMistakes();
      } catch(e) {}
    }

    function filterMistakes(sub, btn) {
      currentFilter = sub;
      document.querySelectorAll('.filter-bar .filter-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      renderMistakes();
    }

    function renderMistakes() {
      const box = document.getElementById('mistakeList');
      const list = currentFilter === 'all' ? allMistakes : allMistakes.filter(m => m.subject === currentFilter);
      if (list.length === 0) {
        box.innerHTML = '<div style="text-align:center; padding:30px; color:var(--muted); font-size:13px;">没有该科目的错题记录 🎉</div>';
        return;
      }
      box.innerHTML = list.map(m => {
        let tagClass = 'tag-math';
        if (m.subject === 'chinese') tagClass = 'tag-chinese';
        if (m.subject === 'english') tagClass = 'tag-english';
        return `
          <div class="mistake-item">
            <div class="mistake-header">
              <span class="tag ${tagClass}">${m.subject_label || m.subject}</span>
              <span style="color:var(--muted);">${m.time}</span>
            </div>
            <div class="mistake-q">${m.question}</div>
            <div class="mistake-answers">
              <div class="ans-wrong">❌ 孩子选择：${m.selected_option}</div>
              <div class="ans-right">✅ 正确答案：${m.correct_option}</div>
            </div>
            ${m.hint ? `<div class="mistake-hint">💡 解析：${m.hint}</div>` : ''}
          </div>
        `;
      }).join('');
    }

    async function clearMistakes() {
      if (confirm('确定要清空所有错题记录吗？')) {
        await apiPost('/api/clear_mistakes');
        loadMistakes();
      }
    }

    async function loadQuestions() {
      try {
        const res = await fetch('/api/questions');
        const qs = await res.json();
        document.getElementById('totalQuestions').innerText = `共 ${qs.length} 题`;
        const box = document.getElementById('questionsList');
        box.innerHTML = qs.map((q, idx) => `
          <div class="mistake-item" style="border-left-color:var(--primary);">
            <div class="mistake-header">
              <span class="tag ${q.subject === 'math' ? 'tag-math' : q.subject === 'chinese' ? 'tag-chinese' : 'tag-english'}">${q.subject_label}</span>
              <span style="color:var(--muted);">#${idx + 1}</span>
            </div>
            <div class="mistake-q">${q.question}</div>
            <div style="font-size:12px; color:var(--muted); margin-top:4px;">
              ${q.options.map((opt, oidx) => `${oidx === q.answer ? '<b>✅ ' + opt + '</b>' : '⚪ ' + opt}`).join(' &nbsp;|&nbsp; ')}
            </div>
          </div>
        `).join('');
      } catch(e) {}
    }

    async function pollStatus() {
      try {
        const res = await fetch('/api/status');
        const data = await res.json();
        
        if (!data.has_tv_ip) {
          document.getElementById('setupBanner').style.display = 'flex';
        } else {
          document.getElementById('setupBanner').style.display = 'none';
          document.getElementById('settingsTvIp').value = data.tv_ip || '';
        }

        const badge = document.getElementById('statusBadge');
        const statusText = document.getElementById('statusText');
        if (data.tv_online) {
          badge.className = 'status-badge';
          statusText.innerText = `电视已在线 (${data.tv_ip})`;
        } else {
          badge.className = 'status-badge offline';
          statusText.innerText = data.has_tv_ip ? '电视未连接' : '未配置电视 IP';
        }

        const isQuiz = data.mode === 'quiz';
        document.getElementById('btnModeQuiz').className = 'mode-btn ' + (isQuiz ? 'active' : '');
        document.getElementById('btnModeManual').className = 'mode-btn ' + (!isQuiz ? 'active' : '');
        document.getElementById('modeDesc').innerText = isQuiz ? '【🎮 答题充值模式 · 语数英混合】' : '【⏱️ 家长掌权模式 · 手动定时】';
        document.getElementById('manualControls').style.display = isQuiz ? 'none' : 'flex';
        document.getElementById('quizProgress').style.display = isQuiz ? 'block' : 'none';
        document.getElementById('quizProgress').innerText = `已答题积攒：${data.earned_minutes} / 30 分钟`;

        const banner = document.getElementById('stateBanner');
        const title = document.getElementById('stateTitle');
        const countdown = document.getElementById('countdown');

        if (data.is_locked) {
          banner.className = 'state-banner locked';
          title.innerText = isQuiz ? '🚫 电视已锁定，正在等待答题充值' : '🚫 电视已全屏锁屏中';
          countdown.innerText = '已锁定';
        } else if (data.timer_active) {
          banner.className = 'state-banner running';
          title.innerText = '⏳ 观影倒计时进行中';
          const m = Math.floor(data.remaining_seconds / 60).toString().padStart(2, '0');
          const s = (data.remaining_seconds % 60).toString().padStart(2, '0');
          countdown.innerText = `${m}:${s}`;
        } else {
          banner.className = 'state-banner';
          title.innerText = '电视正常使用中';
          countdown.innerText = '--:--';
        }
      } catch (e) {}
    }

    setInterval(pollStatus, 1500);
    pollStatus();
    loadMistakes();
  </script>
</body>
</html>
"""

LOCK_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
  <title>电视守护 · 知识充值中心</title>
  <style>
    * { margin:0; padding:0; box-sizing:border-box; }
    html, body {
      background: #080c17;
      color: #ffffff;
      font-family: -apple-system, BlinkMacSystemFont, 'PingFang SC', 'Microsoft YaHei', sans-serif;
      height: 100vh;
      width: 100vw;
      display: flex;
      flex-direction: column;
      justify-content: center;
      align-items: center;
      overflow: hidden;
      user-select: none;
      cursor: none;
    }

    .top-bar {
      position: absolute;
      top: 30px;
      display: flex;
      align-items: center;
      gap: 20px;
      background: rgba(255, 255, 255, 0.08);
      border: 1px solid rgba(255, 255, 255, 0.15);
      padding: 10px 32px;
      border-radius: 40px;
      backdrop-filter: blur(10px);
    }
    .top-title { font-size: 24px; font-weight: 700; color: #94a3b8; }
    .top-val { font-size: 28px; font-weight: 900; color: #38bdf8; }

    .quiz-card {
      background: rgba(30, 41, 59, 0.7);
      border: 2px solid rgba(255, 255, 255, 0.12);
      border-radius: 28px;
      padding: 36px 48px;
      max-width: 85%;
      width: 1100px;
      display: flex;
      flex-direction: column;
      gap: 28px;
      box-shadow: 0 20px 60px rgba(0,0,0,0.6);
      backdrop-filter: blur(20px);
      position: relative;
    }

    .subject-pill {
      align-self: flex-start;
      padding: 8px 24px;
      border-radius: 30px;
      font-size: 22px;
      font-weight: 800;
      letter-spacing: 1px;
    }
    .pill-math { background: #1e3a8a; color: #93c5fd; border: 1px solid #3b82f6; }
    .pill-chinese { background: #831843; color: #fbcfe8; border: 1px solid #ec4899; }
    .pill-english { background: #064e3b; color: #6ee7b7; border: 1px solid #10b981; }

    .question-text {
      font-size: 44px;
      font-weight: 800;
      line-height: 1.35;
      color: #f8fafc;
      text-shadow: 0 2px 10px rgba(0,0,0,0.5);
    }

    .options-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 20px;
    }

    .opt-card {
      background: rgba(15, 23, 42, 0.85);
      border: 3px solid rgba(255, 255, 255, 0.15);
      border-radius: 20px;
      padding: 20px 28px;
      display: flex;
      align-items: center;
      gap: 20px;
      transition: all 0.2s;
    }
    .opt-key {
      background: #334155;
      color: white;
      font-size: 26px;
      font-weight: 900;
      padding: 8px 18px;
      border-radius: 12px;
      display: flex;
      align-items: center;
      justify-content: center;
      min-width: 54px;
      box-shadow: 0 4px 0 #1e293b;
    }
    .opt-text {
      font-size: 32px;
      font-weight: 700;
      color: #e2e8f0;
    }

    .toast-overlay {
      position: absolute;
      inset: 0;
      background: rgba(0,0,0,0.85);
      border-radius: 28px;
      display: none;
      flex-direction: column;
      justify-content: center;
      align-items: center;
      gap: 20px;
      z-index: 100;
    }
    .toast-title { font-size: 64px; font-weight: 900; }
    .toast-sub { font-size: 32px; font-weight: 600; color: #cbd5e1; }
    .toast-correct { color: #4ade80; text-shadow: 0 0 30px rgba(74, 222, 128, 0.5); }
    .toast-wrong { color: #f87171; text-shadow: 0 0 30px rgba(248, 113, 113, 0.5); }

    .manual-lock {
      display: none;
      flex-direction: column;
      align-items: center;
      text-align: center;
    }
    .badge {
      display: inline-flex;
      align-items: center;
      background: rgba(239, 68, 68, 0.18);
      border: 3px solid #ef4444;
      color: #ef4444;
      padding: 14px 42px;
      border-radius: 60px;
      font-size: 34px;
      font-weight: 800;
      margin-bottom: 40px;
    }
    .manual-msg {
      font-size: 78px;
      font-weight: 900;
      line-height: 1.3;
      max-width: 85%;
      margin-bottom: 30px;
    }
  </style>
</head>
<body>

  <div id="manualLockView" class="manual-lock">
    <div class="badge">⏰ 观影时间到 · 屏幕锁定</div>
    <div class="manual-msg" id="manualMsgText">时间到了，该写作业了！</div>
    <div style="font-size:36px; color:#94a3b8; font-weight:600;">（拔插头重启也没用哦，找家长在手机上解锁）</div>
  </div>

  <div id="quizView" style="display:flex; flex-direction:column; align-items:center; width:100%;">
    <div class="top-bar">
      <span class="top-title">知识充值看电视 💡</span>
      <span class="top-title">已积攒观影时长:</span>
      <span class="top-val" id="topEarned">0 / 30 分钟</span>
    </div>

    <div class="quiz-card">
      <div id="subjPill" class="subject-pill pill-math">学科</div>
      <div id="qText" class="question-text">正在从题库加载题目...</div>

      <div class="options-grid">
        <div class="opt-card" id="optCard0">
          <span class="opt-key">⬆️ A</span>
          <span class="opt-text" id="optText0">选项 A</span>
        </div>
        <div class="opt-card" id="optCard1">
          <span class="opt-key">⬇️ B</span>
          <span class="opt-text" id="optText1">选项 B</span>
        </div>
        <div class="opt-card" id="optCard2">
          <span class="opt-key">⬅️ C</span>
          <span class="opt-text" id="optText2">选项 C</span>
        </div>
        <div class="opt-card" id="optCard3">
          <span class="opt-key">➡️ D</span>
          <span class="opt-text" id="optText3">选项 D</span>
        </div>
      </div>

      <div id="toastOverlay" class="toast-overlay">
        <div id="toastTitle" class="toast-title toast-correct">🎉 太棒了！回答正确！</div>
        <div id="toastSub" class="toast-sub">观影时间 +10 分钟</div>
      </div>
    </div>
  </div>

  <div style="position:absolute; bottom:25px; font-size:22px; color:#475569;">
    按遥控器 [上] [下] [左] [右] 键直接作答 · 答对加时 · 答错多练
  </div>

  <script>
    let currentQ = null;
    let isAnsweringBlocked = false;

    function blockSystemKeys(e) {
      if ([19, 20, 21, 22, 38, 40, 37, 39, 49, 50, 51, 52].includes(e.keyCode)) {
        handleUserAnswerKey(e.keyCode);
      }
      e.preventDefault();
      e.stopPropagation();
      return false;
    }

    ['keydown', 'keyup', 'contextmenu'].forEach(evt => {
      window.addEventListener(evt, blockSystemKeys, { capture: true, passive: false });
    });

    function handleUserAnswerKey(code) {
      if (isAnsweringBlocked || !currentQ) return;
      let selected = -1;
      if (code === 19 || code === 38 || code === 49) selected = 0;
      if (code === 20 || code === 40 || code === 50) selected = 1;
      if (code === 21 || code === 37 || code === 51) selected = 2;
      if (code === 22 || code === 39 || code === 52) selected = 3;

      if (selected !== -1) {
        submitAnswer(selected);
      }
    }

    async function loadNextQuestion() {
      try {
        const res = await fetch('/api/random_question');
        currentQ = await res.json();
        if (currentQ && currentQ.question) {
          document.getElementById('qText').innerText = currentQ.question;
          const pill = document.getElementById('subjPill');
          pill.innerText = currentQ.subject_label || '学科';
          pill.className = 'subject-pill ' + (currentQ.subject === 'math' ? 'pill-math' : currentQ.subject === 'chinese' ? 'pill-chinese' : 'pill-english');
          
          for (let i = 0; i < 4; i++) {
            document.getElementById('optText' + i).innerText = currentQ.options[i] || '--';
            document.getElementById('optCard' + i).style.borderColor = 'rgba(255,255,255,0.15)';
          }
        }
      } catch(e) {}
    }

    async function submitAnswer(idx) {
      if (isAnsweringBlocked) return;
      isAnsweringBlocked = true;

      const isCorrect = idx === currentQ.answer;
      const overlay = document.getElementById('toastOverlay');
      const title = document.getElementById('toastTitle');
      const sub = document.getElementById('toastSub');

      if (isCorrect) {
        title.className = 'toast-title toast-correct';
        title.innerText = '🎉 太棒了！回答正确！';
        sub.innerText = '观影时间 +10 分钟 👏';
        overlay.style.display = 'flex';
      } else {
        title.className = 'toast-title toast-wrong';
        title.innerText = '😏 菜就多练！！';
        sub.innerText = '正确答案是: ' + currentQ.options[currentQ.answer] + '（再奖励你一题！）';
        overlay.style.display = 'flex';
      }

      const res = await fetch('/api/answer', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          question_id: currentQ.id,
          selected_idx: idx,
          is_correct: isCorrect
        })
      });
      const data = await res.json();

      setTimeout(() => {
        overlay.style.display = 'none';
        isAnsweringBlocked = false;
        if (data.reached_cap) {
          // 满 30 分钟已通关，自动看电视
        } else {
          loadNextQuestion();
        }
      }, isCorrect ? 1800 : 2500);
    }

    async function checkState() {
      try {
        const res = await fetch('/api/status');
        const data = await res.json();
        
        document.getElementById('topEarned').innerText = `${data.earned_minutes} / 30 分钟`;

        if (data.mode === 'manual') {
          document.getElementById('manualLockView').style.display = 'flex';
          document.getElementById('quizView').style.display = 'none';
          document.getElementById('manualMsgText').innerText = data.message || '时间到了，该写作业了！';
        } else {
          document.getElementById('manualLockView').style.display = 'none';
          document.getElementById('quizView').style.display = 'flex';
        }
      } catch(e) {}
    }

    setInterval(checkState, 2000);
    checkState();
    loadNextQuestion();
  </script>
</body>
</html>
"""

class RequestHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(INDEX_HTML.encode("utf-8"))

        elif path == "/tv-lock":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(LOCK_HTML.encode("utf-8"))

        elif path == "/api/status":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            with state.lock:
                resp = {
                    "mode": state.mode,
                    "is_locked": state.is_locked,
                    "remaining_seconds": state.remaining_seconds,
                    "timer_active": state.timer_active,
                    "earned_minutes": state.earned_minutes,
                    "message": state.message,
                    "tv_online": state.tv_online,
                    "tv_ip": config.get("tv_ip", ""),
                    "has_tv_ip": bool(config.get("tv_ip"))
                }
            self.wfile.write(json.dumps(resp).encode("utf-8"))

        elif path == "/api/random_question":
            q = db.get_random_question()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(q or {}).encode("utf-8"))

        elif path == "/api/questions":
            qs = db.get_questions()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(qs).encode("utf-8"))

        elif path == "/api/mistakes":
            mistakes = db.get_mistakes()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(mistakes).encode("utf-8"))

        elif path == "/api/screenshot":
            temp_path = os.path.join(BASE_DIR, "current_screen.png")
            tv_ip = config.get("tv_ip")
            tv_port = config.get("tv_port", 5555)
            if tv_ip:
                cmd = f'"{ADB_PATH}" -s {tv_ip}:{tv_port} exec-out screencap -p > "{temp_path}"'
                subprocess.run(cmd, shell=True, timeout=5)
            
            if os.path.exists(temp_path) and os.path.getsize(temp_path) > 1000:
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                with open(temp_path, "rb") as f:
                    self.wfile.write(f.read())
            else:
                self.send_response(404)
                self.end_headers()

        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        post_body = self.rfile.read(content_length) if content_length > 0 else b"{}"
        try:
            data = json.loads(post_body.decode("utf-8"))
        except Exception:
            data = {}

        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/config":
            tv_ip = data.get("tv_ip", "").strip()
            if tv_ip:
                config.set_many({"tv_ip": tv_ip})
                ensure_adb_connected()
            self._send_json({"ok": True, "tv_ip": config.get("tv_ip")})

        elif path == "/api/mode":
            mode = data.get("mode", "quiz")
            with state.lock:
                state.mode = mode
                state.save()
            show_lock_screen_on_tv()
            self._send_json({"ok": True, "mode": mode})

        elif path == "/api/answer":
            qid = data.get("question_id")
            selected_idx = data.get("selected_idx")
            is_correct = data.get("is_correct", False)

            qs = db.get_questions()
            q = next((item for item in qs if item["id"] == qid), None)

            reached_cap = False
            if is_correct:
                with state.lock:
                    state.earned_minutes = min(30, state.earned_minutes + 10)
                    if state.earned_minutes >= 30:
                        reached_cap = True
                        state.is_locked = False
                        state.timer_active = True
                        state.remaining_seconds = 30 * 60
                        unlock_tv()
                    state.save()
            else:
                if q:
                    db.record_mistake(q, selected_idx)

            self._send_json({"ok": True, "reached_cap": reached_cap, "earned_minutes": state.earned_minutes})

        elif path == "/api/lock":
            msg = data.get("message")
            with state.lock:
                if msg:
                    state.message = msg
                state.is_locked = True
                state.timer_active = False
                state.remaining_seconds = 0
                state.save()
            show_lock_screen_on_tv()
            self._send_json({"ok": True})

        elif path == "/api/sleep":
            run_adb('shell input keyevent 26')
            self._send_json({"ok": True})

        elif path == "/api/unlock":
            with state.lock:
                state.is_locked = False
                state.timer_active = False
                state.remaining_seconds = 0
                state.save()
            unlock_tv()
            self._send_json({"ok": True})

        elif path == "/api/timer":
            minutes = data.get("minutes", 30)
            msg = data.get("message")
            with state.lock:
                if msg:
                    state.message = msg
                state.remaining_seconds = int(minutes) * 60
                state.timer_active = True
                state.is_locked = False
                state.save()
            unlock_tv()
            self._send_json({"ok": True})

        elif path == "/api/add_time":
            add_mins = data.get("minutes", 10)
            with state.lock:
                state.remaining_seconds += int(add_mins) * 60
                if state.is_locked:
                    state.is_locked = False
                    state.timer_active = True
                    unlock_tv()
                state.save()
            self._send_json({"ok": True})

        elif path == "/api/clear_mistakes":
            db.clear_mistakes()
            self._send_json({"ok": True})

        else:
            self.send_response(404)
            self.end_headers()

    def _send_json(self, data):
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode("utf-8"))

def main():
    threading.Thread(target=guardian_loop, daemon=True).start()
    server_port = config.get("server_port", 3000)
    server = HTTPServer(("0.0.0.0", server_port), RequestHandler)
    print("==================================================")
    print("🗡️ 电视刺客 (TV-Assassin) 开源版已成功启动！")
    print(f">> 电脑管理后台: http://localhost:{server_port}")
    print(f">> 局域网/手机端: http://{LOCAL_IP}:{server_port}")
    print("==================================================")
    server.serve_forever()

if __name__ == "__main__":
    main()
