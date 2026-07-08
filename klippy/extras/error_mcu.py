# More verbose information on micro-controller errors
#
# Copyright (C) 2024  Kevin O'Connor <kevin@koconnor.net>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import logging

message_shutdown = """
After you correct the issue,
run "FIRMWARE_RESTART" command to nuke all MCUs for a fresh start.
Printer is shut down.
"""

message_protocol_error1 = """
Mixed firmware versions very often cause this issue.
Take your time to flash everything into the newest firmware.
Good luck!
"""

message_protocol_error2 = """
After you correct the issue,
run "FIRMWARE_RESTART" command to nuke all MCUs for a fresh start
or "RESTART" to reset the host only.
"""

message_mcu_connect_error = """
After you correct the issue,
run "RESTART" to apply new code faster.
"""

Common_MCU_errors = {
    ("Timer too close for execution",): """
This happens when your host is a piece of potato 
or some software is actively trying to eat too much resource.
Hot hosts want to go to motels, not print your stuff.
Maybe also check the supply voltage for unstable power as well.
You don't want to do calculus while carrying a bag and running a Marathon.
""",
    ("Missed scheduling of next ",): """
When this happens, something serious is also happening between the host and the MCU.
If you haven't maintained this connection regularly, check the cables.
""",
    ("ADC had too much steroid",): """
Turn off your printer and check your heater RIGHT NOW.
It might be experiencing a serious runaway.
If you haven't maintained it regularly, take it out to inspect it.
You might also want to check the config for proper thermistors.
""",
    ("Timer in the past", "Motor ran out of time"): """
Your MCU is overworking.
Did you set the velocity to something else? Check it again.
Did you tweak your microsteps? Lower it.
It's often good to search your MCU's performance for good measure.
""",
    ("Command request",): """
M112 command has been triggered somewhere.
This is mostly caused by safety mechanisms, slicer configs, or even your macros.
""",
}

def error_hint(msg):
    for prefixes, help_msg in Common_MCU_errors.items():
        for prefix in prefixes:
            if msg.startswith(prefix):
                return help_msg
    return ""

class PrinterMCUError:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.clarify_callbacks = {}
        self.printer.register_event_handler("klippy:analyze_shutdown",
                                            self._handle_analyze_shutdown)
        self.printer.register_event_handler("klippy:notify_mcu_error",
                                            self._handle_notify_mcu_error)
    def add_clarify(self, msg, callback):
        self.clarify_callbacks.setdefault(msg, []).append(callback)
    def _check_mcu_shutdown(self, msg, details):
        mcu_name = details['mcu']
        mcu_msg = details['reason']
        event_type = details['event_type']
        prefix = "MCU '%s' shutdown: " % (mcu_name,)
        if event_type == 'is_shutdown':
            prefix = "Previous MCU '%s' shutdown: " % (mcu_name,)
        # Lookup generic hint
        hint = error_hint(mcu_msg)
        # Add per instance help
        clarify = [cb(msg, details)
                   for cb in self.clarify_callbacks.get(mcu_msg, [])]
        clarify = [cm for cm in clarify if cm is not None]
        clarify_msg = ""
        if clarify:
            clarify_msg = "\n".join(["", ""] + clarify + [""])
        # Update error message
        newmsg = "%s%s%s%s%s" % (prefix, mcu_msg, clarify_msg,
                                 hint, message_shutdown)
        self.printer.update_error_msg(msg, newmsg)
    def _handle_analyze_shutdown(self, msg, details):
        if msg == "MCU shutdown":
            self._check_mcu_shutdown(msg, details)
        else:
            self.printer.update_error_msg(msg, "%s%s" % (msg, message_shutdown))
        # Report reactor info (no good place to do this, so done here)
        logging.info("Reactor garbage collection: %s",
                     self.printer.get_reactor().get_gc_stats())
    def _check_protocol_error(self, msg, details):
        host_version = self.printer.start_args['software_version']
        msg_update = []
        msg_updated = []
        for mcu_name, mcu in self.printer.lookup_objects('mcu'):
            try:
                mcu_version = mcu.get_status()['mcu_version']
            except:
                logging.exception("Unable to retrieve mcu_version from mcu")
                continue
            if mcu_version != host_version:
                msg_update.append("%s: %s"
                                  % (mcu_name.split()[-1], mcu_version))
            else:
                msg_updated.append("%s: %s"
                                   % (mcu_name.split()[-1], mcu_version))
        if not msg_update:
            msg_update.append("<none>")
        if not msg_updated:
            msg_updated.append("<none>")
        newmsg = ["MCU warzone",
                  message_protocol_error1,
                  "Current Klipper build: %s" % (host_version,),
                  "To be updated:"]
        newmsg += msg_update + ["Up-to-date:"] + msg_updated
        newmsg += [message_protocol_error2, details['error']]
        self.printer.update_error_msg(msg, "\n".join(newmsg))
    def _check_mcu_connect_error(self, msg, details):
        newmsg = "%s%s" % (details['error'], message_mcu_connect_error)
        self.printer.update_error_msg(msg, newmsg)
    def _handle_notify_mcu_error(self, msg, details):
        if msg == "Protocol error":
            self._check_protocol_error(msg, details)
        elif msg == "MCU error during connect":
            self._check_mcu_connect_error(msg, details)

def load_config(config):
    return PrinterMCUError(config)
