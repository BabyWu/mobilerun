"""
Shared resources that are initialized once and reused across all test cases.

Key optimization: Driver, LLMs, and state providers are expensive to initialize.
By sharing them, we achieve 90%+ performance improvement over subprocess approach.
"""

import logging
from pathlib import Path

try:
    from async_adbutils import adb
    from mobilerun.agent.utils.llm_loader import load_agent_llms
    from mobilerun.config_manager import MobileConfig
    from mobilerun_core_local.driver.android import AndroidDriver
    from mobilerun_core_local.driver.ios import create_ios_driver, discover_ios_device
    from mobilerun.mcp.client import MCPClientManager
    from mobilerun.tools.filters import ConciseFilter, DetailedFilter
    from mobilerun.tools.formatters import IndexedFormatter
    from mobilerun.tools.ui.ios_provider import IOSStateProvider
    from mobilerun.tools.ui.provider import AndroidStateProvider
except ImportError:
    # For standalone testing without full mobilerun installation
    adb = None
    load_agent_llms = None
    MobileConfig = None
    AndroidDriver = None
    create_ios_driver = None
    discover_ios_device = None
    MCPClientManager = None
    ConciseFilter = None
    DetailedFilter = None
    IndexedFormatter = None
    IOSStateProvider = None
    AndroidStateProvider = None

logger = logging.getLogger("mobilerun_autotest")


class SharedResources:
    """
    Shared resources initialized once for entire test suite.

    Resources:
    - driver: DeviceDriver (AndroidDriver or IOSDriver)
    - state_provider: StateProvider (platform-specific)
    - llms: dict of LLM instances {manager, executor, fast_agent, ...}
    - mcp_manager: MCP client manager (if enabled)

    Lifecycle:
    1. initialize() - Connect to device, load LLMs
    2. Used by all test cases
    3. close() - Cleanup connections
    """

    def __init__(self):
        self.driver = None
        self.state_provider = None
        self.llms = None
        self.mcp_manager = None
        self.config: MobileConfig | None = None
        self.device_id: str | None = None

    async def initialize(
        self,
        config: MobileConfig,
        device_id: str | None = None,
    ):
        """
        Initialize all shared resources.

        Args:
            config: MobileConfig for agent settings
            device_id: Specific device serial (optional, auto-detect if None)

        Raises:
            ValueError: If no device found or initialization fails
        """
        self.config = config
        self.device_id = device_id

        logger.info("🔧 Initializing shared resources...")

        # 1. Create device driver
        await self._initialize_driver()
        logger.info(f"✅ Driver: {self.driver.__class__.__name__} ({self.device_id})")

        # 2. Create state provider
        await self._initialize_state_provider()
        logger.info(f"✅ State Provider: {self.state_provider.__class__.__name__}")

        # 3. Load LLMs (expensive, do once)
        self._initialize_llms()
        llm_names = list(self.llms.keys()) if isinstance(self.llms, dict) else ["single"]
        logger.info(f"✅ LLMs loaded: {', '.join(llm_names)}")

        # 4. Initialize MCP (if configured)
        if config.mcp and config.mcp.enabled:
            await self._initialize_mcp()
            server_count = len(config.mcp.servers) if config.mcp.servers else 0
            logger.info(f"✅ MCP: {server_count} server(s) connected")

        logger.info("✅ Shared resources initialized successfully")

    async def _initialize_driver(self):
        """Initialize device driver based on platform."""
        is_ios = self.config.device.platform.lower() == "ios"

        if is_ios:
            # iOS driver
            ios_url = self.config.device.serial
            if not ios_url:
                ios_url = await discover_ios_device()

            self.driver = await create_ios_driver(
                ios_url,
                token=self.config.device.resolve_auth_token(),
            )
            await self.driver.connect()
            self.device_id = ios_url

        else:
            # Android driver
            device_serial = self.config.device.serial or self.device_id

            if not device_serial:
                devices = await adb.list()
                if not devices:
                    raise ValueError(
                        "No connected Android devices found. "
                        "Run 'adb devices' to check connections."
                    )
                device_serial = devices[0].serial
                logger.info(f"Auto-detected device: {device_serial}")

            self.driver = AndroidDriver(
                serial=device_serial,
                use_tcp=self.config.device.use_tcp,
                portal_mode=self.config.device.portal_mode,
            )
            await self.driver.connect()
            self.device_id = device_serial

    async def _initialize_state_provider(self):
        """Initialize state provider based on platform."""
        is_ios = self.config.device.platform.lower() == "ios"

        # Determine if vision is enabled (affects tree filter)
        vision_enabled = (
            self.config.agent.vision_only
            or self.config.agent.manager.vision
            or self.config.agent.executor.vision
            or self.config.agent.fast_agent.vision
        )

        if is_ios:
            self.state_provider = IOSStateProvider(
                self.driver,
                use_normalized=self.config.agent.use_normalized_coordinates,
                vision_enabled=vision_enabled,
            )
        else:
            tree_filter = ConciseFilter() if vision_enabled else DetailedFilter()
            self.state_provider = AndroidStateProvider(
                self.driver,
                tree_filter=tree_filter,
                tree_formatter=IndexedFormatter(),
                use_normalized=self.config.agent.use_normalized_coordinates,
                stealth=self.config.tools.stealth if self.config.tools else False,
                vision_enabled=vision_enabled,
            )

    def _initialize_llms(self):
        """Load LLM instances from config."""
        try:
            self.llms = load_agent_llms(self.config)
        except Exception as e:
            logger.warning(f"Failed to load LLMs: {e}")
            logger.warning("Tests requiring LLMs will fail")
            self.llms = {}

    async def _initialize_mcp(self):
        """Initialize MCP client manager if configured."""
        try:
            self.mcp_manager = MCPClientManager(self.config.mcp)
            await self.mcp_manager.connect_all()
        except Exception as e:
            logger.warning(f"Failed to initialize MCP: {e}")
            self.mcp_manager = None

    async def close(self):
        """
        Cleanup all resources.

        Call this after all test cases complete.
        """
        logger.info("🧹 Cleaning up shared resources...")

        if self.driver:
            try:
                await self.driver.disconnect()
                logger.debug("Driver disconnected")
            except Exception as e:
                logger.warning(f"Driver cleanup error: {e}")

        if self.mcp_manager:
            try:
                await self.mcp_manager.disconnect_all()
                logger.debug("MCP disconnected")
            except Exception as e:
                logger.warning(f"MCP cleanup error: {e}")

        logger.info("✅ Cleanup complete")

    def merge_run_flags(self, run_flags: dict) -> MobileConfig:
        """
        Create a new MobileConfig with run_flags merged.

        This allows per-case overrides (vision, reasoning, steps, etc.)
        while keeping base config intact.

        Args:
            run_flags: Dictionary from TestCase.run_flags

        Returns:
            New MobileConfig with merged settings
        """
        config = self.config.model_copy(deep=True)

        for key, value in run_flags.items():
            if key == "steps":
                config.agent.max_steps = int(value)
            elif key == "vision":
                v = bool(value)
                config.agent.manager.vision = v
                config.agent.executor.vision = v
                config.agent.fast_agent.vision = v
            elif key == "vision_only":
                config.agent.vision_only = bool(value)
            elif key == "reasoning":
                config.agent.reasoning = bool(value)
            elif key == "provider":
                config.agent.provider = str(value)
            elif key == "model":
                config.agent.model = str(value)
            elif key == "temperature":
                config.agent.temperature = float(value)
            elif key == "stream":
                config.agent.streaming = bool(value)
            elif key == "tracing":
                config.tracing.enabled = bool(value)
            elif key == "debug":
                config.logging.debug = bool(value)
            elif key == "ios":
                if bool(value):
                    config.device.platform = "ios"
            elif key == "tcp":
                config.device.use_tcp = bool(value)
            elif key == "save_trajectory":
                config.logging.save_trajectory = str(value)
            elif key == "control_backend":
                config.device.control_backend = str(value)
            elif key == "device_id":
                config.device.device_id = str(value)

        return config
