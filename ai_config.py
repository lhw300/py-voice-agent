# config/ai_config.py
#
# Java: package com.lcallai;
#
# Java: import java.io.BufferedReader;
# Java: import java.io.FileReader;
# Java: import java.util.Map;
# Java: import java.util.concurrent.ConcurrentHashMap;
import logging                        # Java: import org.apache.logging.log4j.*
import os
from typing import Dict, Optional

# Java: private static final Logger logger = LogManager.getLogger(AiConfig.class);
logger = logging.getLogger(__name__)


# ===========================================================================
# Java: public class AiConfig {
# ===========================================================================

# Java: public static String configPath = null;
configPath: Optional[str] = None

# Java: public static String configFile;
configFile: Optional[str] = None

# Java: private static final Map<String, String> configMap = new ConcurrentHashMap<>();
configMap: Dict[str, str] = {}


# ---------------------------------------------------------------------------
# Java: public static synchronized void init(String filePath) {
# Java:     configPath = filePath;
# Java:     configPath = filePath.replace("\\", "/");
# Java:     configFile = filePath + "/config/ai.conf";
# Java:     reload();
# Java: }
# ---------------------------------------------------------------------------
def init(filePath: str) -> None:
    global configPath, configFile

    # Java: configPath = filePath;
    # Java: configPath = filePath.replace("\\", "/");
    configPath = filePath.replace("\\", "/")

    # Java: configFile = filePath + "/config/ai.conf";
    configFile = configPath + "/config/ai.conf"

    # Java: reload();
    reload()


# ---------------------------------------------------------------------------
# Java: public static synchronized void reload() {
# Java:     if (configFile == null) {
# Java:         throw new RuntimeException("AiConfig not initialized");
# Java:     }
# Java:     try {
# Java:         Map<String, String> newMap = new ConcurrentHashMap<>();
# Java:         BufferedReader reader = new BufferedReader(new FileReader(configFile));
# Java:         String line;
# Java:         while ((line = reader.readLine()) != null) {
# Java:             line = line.trim();
# Java:             if (line.isEmpty()) continue;
# Java:             if (line.startsWith("#")) continue;
# Java:             int idx = line.indexOf('=');
# Java:             if (idx < 0) continue;
# Java:             String key   = line.substring(0, idx).trim();
# Java:             String value = line.substring(idx + 1).trim();
# Java:             newMap.put(key, value);
# Java:         }
# Java:         reader.close();
# Java:         configMap.clear();
# Java:         configMap.putAll(newMap);
# Java:         logger.debug("AiConfig loaded: " + configMap.size());
# Java:     } catch (Exception e) {
# Java:         throw new RuntimeException("Load config error: " + e.getMessage(), e);
# Java:     }
# Java: }
# ---------------------------------------------------------------------------
def reload() -> None:
    global configMap

    # Java: if (configFile == null) throw new RuntimeException("AiConfig not initialized");
    if configFile is None:
        raise RuntimeError("AiConfig not initialized")

    try:
        # Java: Map<String, String> newMap = new ConcurrentHashMap<>();
        newMap: Dict[str, str] = {}

        # Java: BufferedReader reader = new BufferedReader(new FileReader(configFile));
        with open(configFile, "r", encoding="utf-8") as reader:

            # Java: while ((line = reader.readLine()) != null) {
            for line in reader:

                # Java: line = line.trim();
                line = line.strip()

                # Java: if (line.isEmpty()) continue;
                if not line:
                    continue

                # Java: if (line.startsWith("#")) continue;
                if line.startswith("#"):
                    continue

                # Java: int idx = line.indexOf('=');
                idx = line.find("=")

                # Java: if (idx < 0) continue;
                if idx < 0:
                    continue

                # Java: String key   = line.substring(0, idx).trim();
                # Java: String value = line.substring(idx + 1).trim();
                key   = line[:idx].strip()
                value = line[idx + 1:].strip()

                # Java: newMap.put(key, value);
                newMap[key] = value

        # Java: configMap.clear(); configMap.putAll(newMap);
        configMap.clear()
        configMap.update(newMap)

        # Java: logger.debug("AiConfig loaded: " + configMap.size());
        logger.debug("AiConfig loaded: " + str(len(configMap)))

    # Java: } catch (Exception e) {
    except Exception as e:
        # Java: throw new RuntimeException("Load config error: " + e.getMessage(), e);
        raise RuntimeError("Load config error: " + str(e)) from e


# ---------------------------------------------------------------------------
# Java: private static String get(String key) {
# Java:     return configMap.get(key);
# Java: }
# ---------------------------------------------------------------------------
def _get(key: str) -> Optional[str]:
    v = configMap.get(key)
    if v is None:
        return None
    # strip inline comments
    if "#" in v:
        v = v[:v.index("#")]
    return v.strip() or None


# ---------------------------------------------------------------------------
# Java: public static String getStringConfig(String key, String defaultValue) {
# Java:     String value = get(key);
# Java:     if (value != null && !value.trim().isEmpty()) {
# Java:         return value.trim();
# Java:     }
# Java:     return defaultValue;
# Java: }
# ---------------------------------------------------------------------------
def getStringConfig(key: str, defaultValue: str) -> str:
    value = _get(key)
    # Java: if (value != null && !value.trim().isEmpty()) return value.trim();
    if value is not None and value.strip():
        return value.strip()
    # Java: return defaultValue;
    return defaultValue


# ---------------------------------------------------------------------------
# Java: public static int getIntConfig(String key, int defaultValue) {
# Java:     String v = get(key);
# Java:     if (v == null || v.trim().isEmpty()) return defaultValue;
# Java:     try {
# Java:         return Integer.parseInt(v);
# Java:     } catch (Exception e) {
# Java:         return defaultValue;
# Java:     }
# Java: }
# ---------------------------------------------------------------------------
def getIntConfig(key: str, defaultValue: int) -> int:
    v = _get(key)
    # Java: if (v == null || v.trim().isEmpty()) return defaultValue;
    if v is None or not v.strip():
        return defaultValue
    # Java: try { return Integer.parseInt(v); } catch (Exception e) { return defaultValue; }
    try:
        return int(v.strip())
    except Exception:
        return defaultValue


# ---------------------------------------------------------------------------
# Java: public static double getDoubleConfig(String key, double defaultValue) {
# Java:     String v = get(key);
# Java:     if (v == null || v.trim().isEmpty()) return defaultValue;
# Java:     try {
# Java:         return Double.parseDouble(v);
# Java:     } catch (Exception e) {
# Java:         return defaultValue;
# Java:     }
# Java: }
# ---------------------------------------------------------------------------
def getDoubleConfig(key: str, defaultValue: float) -> float:
    v = _get(key)
    # Java: if (v == null || v.trim().isEmpty()) return defaultValue;
    if v is None or not v.strip():
        return defaultValue
    # Java: try { return Double.parseDouble(v); } catch (Exception e) { return defaultValue; }
    try:
        return float(v.strip())
    except Exception:
        return defaultValue


# ---------------------------------------------------------------------------
# Java: public static boolean getBooleanConfig(String key, boolean defaultValue) {
# Java:     String v = get(key);
# Java:     if (v == null || v.trim().isEmpty()) return defaultValue;
# Java:     return v.equalsIgnoreCase("true")
# Java:         || v.equalsIgnoreCase("1")
# Java:         || v.equalsIgnoreCase("yes");
# Java: }
# ---------------------------------------------------------------------------
def getBooleanConfig(key: str, defaultValue: bool) -> bool:
    v = _get(key)
    # Java: if (v == null || v.trim().isEmpty()) return defaultValue;
    if v is None or not v.strip():
        return defaultValue
    # Java: return v.equalsIgnoreCase("true") || v.equalsIgnoreCase("1") || v.equalsIgnoreCase("yes");
    return v.strip().lower() in ("true", "1", "yes")
def log(logger, key: str, label: str, text: str, sinfo: str = "") -> None:
    """
    Conditional logger controlled by ai.conf.
    key   : config key, e.g. "log.fullctx.chars"
    label : log prefix, e.g. "fullCtx"
    text  : content to log
    sinfo : session info prefix (optional)
    """
    n = getIntConfig(key, 0)
    if n > 0:
        logger.debug(sinfo + label + ": " + str(text)[:n])