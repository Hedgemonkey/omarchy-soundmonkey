import subprocess
import json
import logging


class SinkManager:
    def __init__(self, headset_sink_substrings=()):
        """headset_sink_substrings: substrings (typically each configured
        device's sink_match) identifying a sink as belonging to a priority
        headset, so set_internal_auto() knows to skip it and pick a real
        "internal" output instead. Driven by config rather than a hardcoded
        device list, so adding a device needs no change here."""
        self.last_sink = None
        self.last_source = None
        self._headset_sink_substrings = tuple(s for s in headset_sink_substrings if s)

    def _get_nodes(self, media_class):
        out = subprocess.check_output(["pw-dump"], stderr=subprocess.DEVNULL, timeout=5.0)
        nodes = json.loads(out)
        result = {}
        for obj in nodes:
            props = obj.get("info", {}).get("props", {})
            if props.get("media.class") == media_class:
                desc = props.get("node.description", props.get("node.name"))
                result[desc] = obj["id"]
        return result

    def _get_sinks(self):
        return self._get_nodes("Audio/Sink")

    def _get_sources(self):
        return self._get_nodes("Audio/Source")

    def set_default_by_description_substr(self, substr):
        sinks = self._get_sinks()
        for desc, nid in sinks.items():
            if substr in (desc or ""):
                logging.info(f"Setting default sink to {desc} (id {nid})")
                subprocess.run(["wpctl", "set-default", str(nid)], check=False)
                self.last_sink = desc
                return True
        logging.warning(f"No sink matching substring '{substr}'")
        return False

    def set_default_source_by_description_substr(self, substr):
        sources = self._get_sources()
        for desc, nid in sources.items():
            if substr in (desc or ""):
                logging.info(f"Setting default source to {desc} (id {nid})")
                subprocess.run(["wpctl", "set-default", str(nid)], check=False)
                self.last_source = desc
                return True
        logging.warning(f"No source matching substring '{substr}'")
        return False

    def set_internal_auto(self):
        sinks = self._get_sinks()
        if not sinks:
            logging.warning("No sinks found for internal_auto fallback")
            return False

        def is_headset(desc):
            d = desc or ""
            return any(substr in d for substr in self._headset_sink_substrings)

        non_headset = {d: i for d, i in sinks.items() if not is_headset(d)}
        if not non_headset:
            logging.info("internal_auto: only headset sinks present; leaving default unchanged")
            return False

        analog_candidates = [d for d in non_headset.keys() if "Analog Stereo" in (d or "")]
        analog_filtered = [d for d in analog_candidates if "HDMI" not in d]

        if analog_filtered:
            chosen = analog_filtered[0]
        elif analog_candidates:
            chosen = analog_candidates[0]
        else:
            chosen = list(non_headset.keys())[0]

        nid = non_headset[chosen]
        logging.info(f"Setting default sink (internal_auto) to {chosen} (id {nid})")
        subprocess.run(["wpctl", "set-default", str(nid)], check=False)
        self.last_sink = chosen
        return True

    def set_internal_match(self, substr):
        sinks = self._get_sinks()
        for desc, nid in sinks.items():
            if substr in (desc or ""):
                logging.info(f"Setting default sink (internal_match) to {desc} (id {nid})")
                subprocess.run(["wpctl", "set-default", str(nid)], check=False)
                self.last_sink = desc
                return True
        logging.warning(f"internal_match: no sink found containing '{substr}'")
        return False
