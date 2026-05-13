import os
import queue
import threading
import uuid
import json
from flask import Flask, render_template, request, jsonify, Response

app = Flask(__name__)


class CaptureQueue:
    """FIFO 排队调度器：同一个时间只允许一个抓取任务运行，后续请求排队等待"""

    def __init__(self):
        self._lock = threading.Lock()
        self._waiting = []
        self._client_queues = {}
        self._current_task = None
        self._current_session = None

    def add_client(self):
        """新客户端加入排队，返回 queue_id"""
        qid = str(uuid.uuid4())[:8]
        with self._lock:
            self._waiting.append(qid)
            self._client_queues[qid] = queue.Queue()
            position = len(self._waiting)
            self._client_queues[qid].put({
                "status": "queued",
                "position": position,
                "ahead": position - 1,
            })
            if position == 1 and self._current_task is None:
                self._start_next()
        return qid

    def _start_next(self):
        """启动下一个排队客户端的抓取任务"""
        if not self._waiting:
            return
        qid = self._waiting[0]
        self._current_task = qid
        t = threading.Thread(target=self._run_capture, args=(qid,), daemon=True)
        t.start()

    def _run_capture(self, qid):
        """在独立线程中执行抓取流程，状态通过消息队列推送给 SSE 客户端"""
        from capture import CaptureSession

        session = CaptureSession()
        self._current_session = session
        try:
            qr = session.start_browser()
            if qid not in self._client_queues:
                return
            self._client_queues[qid].put({"status": "active", "qr_image": qr})

            session.wait_for_login(timeout=300)
            if qid not in self._client_queues:
                return
            self._client_queues[qid].put({"status": "capturing"})

            data = session.capture_data()
            if qid not in self._client_queues:
                return
            self._client_queues[qid].put({"status": "done", "data": data})

        except TimeoutError:
            if qid in self._client_queues:
                self._client_queues[qid].put({
                    "status": "timeout",
                    "message": "扫码登录超时（5分钟），请重新开始",
                })
        except Exception as e:
            if qid in self._client_queues:
                self._client_queues[qid].put({
                    "status": "error",
                    "message": str(e),
                })
        finally:
            session.close()
            self._release(qid)

    def _release(self, qid):
        """释放当前任务，启动下一个排队者，更新所有排队者位置"""
        with self._lock:
            if self._current_task == qid:
                self._current_task = None
                self._current_session = None
            if qid in self._waiting:
                self._waiting.remove(qid)
            self._start_next()
            for i, wqid in enumerate(self._waiting):
                if wqid in self._client_queues:
                    self._client_queues[wqid].put({
                        "status": "queued",
                        "position": i + 1,
                        "ahead": i,
                    })

    def get_messages(self, qid):
        """SSE 消息生成器：阻塞读取客户端消息队列，超时发送心跳"""
        while True:
            try:
                msg = self._client_queues[qid].get(timeout=30)
                yield msg
                if msg["status"] in ("done", "error", "timeout"):
                    break
            except queue.Empty:
                yield {"status": "heartbeat"}

    def remove_client(self, qid):
        """客户端断开 SSE 连接时清理"""
        with self._lock:
            if qid in self._waiting:
                self._waiting.remove(qid)
            if qid in self._client_queues:
                del self._client_queues[qid]
            if self._current_task == qid:
                self._current_task = None
                self._current_session = None
                self._start_next()
            for i, wqid in enumerate(self._waiting):
                if wqid in self._client_queues:
                    self._client_queues[wqid].put({
                        "status": "queued",
                        "position": i + 1,
                        "ahead": i,
                    })


capture_queue = CaptureQueue()


@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload():
    """接收用户上传的 JSON 文件并返回内容"""
    if 'file' not in request.files:
        return jsonify({'error': '未找到上传文件'}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': '文件名为空'}), 400
    try:
        content = file.read().decode('utf-8')
        return jsonify({'data': content})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/capture/start', methods=['POST'])
def capture_start():
    """用户请求自动抓取，返回排队 ID"""
    qid = capture_queue.add_client()
    return jsonify({"queue_id": qid})


@app.route('/capture/status')
def capture_status():
    """SSE 端点：持续推送排队/二维码/抓取完成等状态"""
    qid = request.args.get("queue_id", "")
    if qid not in capture_queue._client_queues:
        return jsonify({"error": "无效的队列 ID"}), 400

    def generate():
        try:
            for msg in capture_queue.get_messages(qid):
                yield f"data: {json.dumps(msg, ensure_ascii=False)}\n\n"
                if msg["status"] in ("done", "error", "timeout"):
                    break
        except GeneratorExit:
            capture_queue.remove_client(qid)

    response = Response(generate(), mimetype="text/event-stream")
    response.headers["Cache-Control"] = "no-cache"
    response.headers["X-Accel-Buffering"] = "no"
    return response


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
