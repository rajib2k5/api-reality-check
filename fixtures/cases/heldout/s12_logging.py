import logging
logging.basicConfig(level=logging.INFO, format="%(message)s", force=True)
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
h = logging.StreamHandler()
h.setFormatter(logging.Formatter(fmt="%(levelname)s %(message)s", datefmt="%H:%M"))
logger.addHandler(h)
logger.info("x %s", 1, extra={"k": 1}, stacklevel=1)
logger.warning("w", exc_info=False)
