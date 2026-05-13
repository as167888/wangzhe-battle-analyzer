import time
import base64
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout


class CaptureSession:
    """管理一次完整的战绩抓取会话：启动浏览器 → QR 码 → 等待登录 → 拦截数据"""

    def __init__(self):
        self._playwright = None
        self._browser = None
        self._page = None
        self._data = None

    def start_browser(self):
        """启动无头浏览器，打开王者荣耀历史战绩页面，返回页面截图 base64（含二维码）"""
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
            ],
        )
        self._page = self._browser.new_page(viewport={"width": 1280, "height": 800})
        self._page.goto("https://pvp.qq.com/web201605/hisrecord.shtml",
                        wait_until="networkidle", timeout=30000)
        self._page.wait_for_timeout(3000)
        screenshot = self._page.screenshot(type="png")
        self._setup_response_handler()
        return base64.b64encode(screenshot).decode()

    def _setup_response_handler(self):
        """尽早注册响应拦截器，登录完成后数据请求一来就能捕获"""
        def on_response(response):
            if self._data:
                return
            try:
                if response.request.resource_type in ("fetch", "xhr", "script"):
                    text = response.text()
                    if "AcntName2" in text:
                        self._data = text
            except Exception:
                pass

        self._page.on("response", on_response)

    def wait_for_login(self, timeout=300):
        """轮询等待用户扫码登录完成（URL 变化 或 已拦截到数据 或 页面 DOM 变化）"""
        start = time.time()
        while time.time() - start < timeout:
            # 数据已截获说明登录成功且战绩已加载
            if self._data:
                return
            url = self._page.url
            if "hisrecord" in url and "login" not in url:
                return
            try:
                self._page.wait_for_selector(".user", timeout=2000)
                return
            except Exception:
                pass
            time.sleep(2)
        raise TimeoutError("扫码登录超时，请重试")

    def capture_data(self):
        """登录完成后获取战绩 JSON 数据"""
        if self._data:
            return self._data
        # 数据还没到达，刷新触发请求
        self._page.reload(wait_until="networkidle")
        start = time.time()
        while not self._data and time.time() - start < 30:
            self._page.wait_for_timeout(500)
        if self._data:
            return self._data
        raise Exception("未捕获到战绩数据，请确认该账号有战绩记录")

    def close(self):
        """释放浏览器资源"""
        try:
            if self._browser:
                self._browser.close()
            if self._playwright:
                self._playwright.stop()
        except Exception:
            pass
