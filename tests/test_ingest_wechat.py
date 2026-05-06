import tempfile
import unittest
from pathlib import Path

import quant_llm_wiki.ingest.wechat as mod


class IngestWechatArticleTests(unittest.TestCase):
    def test_classify_allocation(self) -> None:
        content_type = mod.classify_content(
            "行业轮动模型在行业及主题 ETF 配置上的应用",
            "本文讨论ETF配置、行业轮动和再平衡。",
        )
        self.assertEqual(content_type, "allocation")

    def test_classify_strategy(self) -> None:
        content_type = mod.classify_content(
            "均值回归策略",
            "使用开仓、平仓、止损和回测框架评估该策略。",
        )
        self.assertEqual(content_type, "strategy")

    def test_classify_risk_control(self) -> None:
        content_type = mod.classify_content(
            "组合风险预算与回撤控制框架",
            "本文讨论风险预算、回撤控制和波动率目标。",
        )
        self.assertEqual(content_type, "risk_control")

    def test_classify_market_review(self) -> None:
        content_type = mod.classify_content(
            "三月市场复盘",
            "本周市场观察与月报点评。",
        )
        self.assertEqual(content_type, "market_review")

    def test_slugify(self) -> None:
        self.assertEqual(mod.slugify("行业轮动 / ETF 配置"), "行业轮动_etf_配置")

    def test_slugify_replaces_fullwidth_invalid_chars(self) -> None:
        self.assertEqual(
            mod.slugify("华泰 | 金工：红利因子择时与2025Q1行业ETF投资建议"),
            "华泰_金工_红利因子择时与2025q1行业etf投资建议",
        )

    def test_normalize_date_returns_empty_for_non_date_text(self) -> None:
        self.assertEqual(mod.normalize_date("华泰 | 金工：红利因子择时与2025Q1行业ETF投资建议"), "")

    def test_article_dir_name_falls_back_to_today_when_publish_date_invalid(self) -> None:
        article = mod.ArticleData(
            title="华泰 | 金工：红利因子择时与2025Q1行业ETF投资建议",
            source_url="https://mp.weixin.qq.com/s/test",
            account="",
            author="",
            publish_date="华泰 | 金工：红利因子择时与2025Q1行业ETF投资建议",
            raw_html="",
            main_content="",
            content_type="methodology",
            image_urls=[],
            summary="",
            research_question="",
            core_hypothesis="",
            signal_framework="",
            code_blocks=[],
        )
        name = mod.article_dir_name(article)
        self.assertRegex(name, r"^\d{4}-\d{2}-\d{2}_.+_[0-9a-f]{8}$")
        self.assertNotIn("|", name)
        self.assertNotIn("：", name)

    def test_article_dir_name_is_shorter_and_stable(self) -> None:
        article = mod.ArticleData(
            title="【AI量化第24篇】KhQuant 策略框架深度解析：让策略开发回归本质——基于miniQMT的量化交易回测系统开发实记",
            source_url="https://mp.weixin.qq.com/s/test",
            account="",
            author="",
            publish_date="2026-04-02",
            raw_html="",
            main_content="",
            content_type="methodology",
            image_urls=[],
            summary="",
            research_question="",
            core_hypothesis="",
            signal_framework="",
            code_blocks=[],
        )
        name = mod.article_dir_name(article)
        self.assertTrue(name.startswith("2026-04-02_"))
        self.assertLessEqual(len(name), 60)
        self.assertTrue(name.endswith(mod.short_hash(article.title, article.source_url)))

    def test_template_path_for_strategy(self) -> None:
        self.assertTrue(str(mod.template_path_for("strategy")).endswith("strategy-note-template.md"))

    def test_resolve_protocol_relative_image_url(self) -> None:
        resolved = mod.resolve_url("//mmbiz.qpic.cn/example.png", "https://mp.weixin.qq.com/s/abc")
        self.assertEqual(resolved, "https://mmbiz.qpic.cn/example.png")

    def test_extract_image_urls(self) -> None:
        html = """
        <html><body><div id=\"js_content\">
        <img data-src=\"//mmbiz.qpic.cn/a.png\" />
        <img src=\"https://mmbiz.qpic.cn/b.png\" />
        <img data-src=\"//mmbiz.qpic.cn/a.png\" />
        </div></body></html>
        """
        soup = mod.BeautifulSoup(html, "html.parser")
        urls = mod.extract_image_urls(soup.find(id="js_content"), "https://mp.weixin.qq.com/s/test")
        self.assertEqual(
            urls,
            ["https://mmbiz.qpic.cn/a.png", "https://mmbiz.qpic.cn/b.png"],
        )

    def test_extract_code_blocks_prefers_pre(self) -> None:
        html = """
        <html><body><div id=\"js_content\">
        <pre class=\"language-python\">print('hello')\nprint('world')</pre>
        <code>print('hello')</code>
        <code>print('world')</code>
        </div></body></html>
        """
        soup = mod.BeautifulSoup(html, "html.parser")
        blocks = mod.extract_code_blocks(soup.find(id="js_content"))
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0].language, "python")
        self.assertIn("print('world')", blocks[0].content)

    def test_extract_code_blocks_filters_inline_code(self) -> None:
        html = """
        <html><body><div id=\"js_content\">
        <code>seq_len</code>
        <code>num_samples</code>
        <code>return x + y</code>
        </div></body></html>
        """
        soup = mod.BeautifulSoup(html, "html.parser")
        blocks = mod.extract_code_blocks(soup.find(id="js_content"))
        self.assertEqual(len(blocks), 0)

    def test_extract_main_content_removes_code_blocks(self) -> None:
        html = """
        <html><body><div id=\"js_content\">
        <p>第一段说明。</p>
        <pre class=\"language-python\">print('hello')\nprint('world')</pre>
        <p>第二段说明。</p>
        <code>return x + y</code>
        </div></body></html>
        """
        soup = mod.BeautifulSoup(html, "html.parser")
        text = mod.extract_main_content(soup.find(id="js_content"))
        self.assertIn("第一段说明", text)
        self.assertIn("第二段说明", text)
        self.assertNotIn("print('hello')", text)
        self.assertNotIn("return x + y", text)

    def test_build_summary(self) -> None:
        summary = mod.build_summary("第一段内容很重要。\n\n第二段补充说明。\n\n第三段不需要。")
        self.assertIn("第一段内容很重要", summary)
        self.assertIn("第二段补充说明", summary)

    def test_inject_image_section(self) -> None:
        rendered = mod.inject_image_section(
            "```markdown\n![caption](images/001.png)\n```",
            ["![image_1](images/001.png)", "![image_2](images/002.png)"],
        )
        self.assertIn("![image_1](images/001.png)", rendered)
        self.assertIn("![image_2](images/002.png)", rendered)

    def test_render_code_blocks(self) -> None:
        rendered = mod.render_code_blocks([mod.ExtractedCodeBlock(language="python", content="print(1)")])
        self.assertIn("### Code 1", rendered)
        self.assertIn("```python", rendered)

    def test_normalize_url_line(self) -> None:
        self.assertEqual(
            mod.normalize_url_line("https://mp.weixin.qq.com/s/example；"),
            "https://mp.weixin.qq.com/s/example",
        )

    def test_load_url_list_deduplicates_and_cleans(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "urls.txt"
            path.write_text(
                "https://mp.weixin.qq.com/s/a；\n\nhttps://mp.weixin.qq.com/s/b\nhttps://mp.weixin.qq.com/s/a\n",
                encoding="utf-8",
            )
            urls = mod.load_url_list(str(path))
            self.assertEqual(
                urls,
                ["https://mp.weixin.qq.com/s/a", "https://mp.weixin.qq.com/s/b"],
            )

    def test_detect_blocked_wechat_page_raises(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "verification/blocked page"):
            mod.detect_blocked_wechat_page("环境异常 当前环境异常，完成验证后即可继续访问。 去验证")


    def test_classify_ingest_error(self) -> None:
        self.assertEqual(
            mod.classify_ingest_error("wechat returned a verification/blocked page instead of the article content"),
            "blocked_wechat_page",
        )
        self.assertEqual(mod.classify_ingest_error("download failed"), "ingest_error")

    def test_write_ingest_failures(self) -> None:
        original_path = mod.INGEST_FAILURES_PATH
        with tempfile.TemporaryDirectory() as tmpdir:
            mod.INGEST_FAILURES_PATH = Path(tmpdir) / "ingest_failures.txt"
            results = [
                mod.BatchResult(url="https://mp.weixin.qq.com/s/a", success=False, error="download failed"),
                mod.BatchResult(
                    url="https://mp.weixin.qq.com/s/b",
                    success=False,
                    error="wechat returned a verification/blocked page instead of the article content",
                ),
                mod.BatchResult(url="https://mp.weixin.qq.com/s/c", success=True),
            ]
            try:
                output = mod.write_ingest_failures(results)
                content = output.read_text(encoding="utf-8")
            finally:
                mod.INGEST_FAILURES_PATH = original_path
            self.assertIn("https://mp.weixin.qq.com/s/a	ingest_error	download failed", content)
            self.assertIn(
                "https://mp.weixin.qq.com/s/b	blocked_wechat_page	wechat returned a verification/blocked page instead of the article content",
                content,
            )

if __name__ == "__main__":
    unittest.main()

