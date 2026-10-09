import logging

from core import logging_config


def test_app_logger_writes_tracebacks_to_terminal_and_file(tmp_path, monkeypatch, capsys):
    logger = logging.getLogger("learning_path")
    original_handlers = list(logger.handlers)
    for handler in original_handlers:
        logger.removeHandler(handler)
        handler.close()
    monkeypatch.setattr(logging_config, "PROJECT_ROOT", tmp_path)

    try:
        configured = logging_config.configure_app_logging()
        try:
            raise RuntimeError("study plan rendering failure")
        except RuntimeError:
            configured.exception("Unhandled page error")

        contents = (tmp_path / "logs" / "app.log").read_text(encoding="utf-8")
        terminal = capsys.readouterr().err
        assert "Unhandled page error" in contents
        assert "RuntimeError: study plan rendering failure" in contents
        assert "RuntimeError: study plan rendering failure" in terminal
    finally:
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            handler.close()
        for handler in original_handlers:
            logger.addHandler(handler)
