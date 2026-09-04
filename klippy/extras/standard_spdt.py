# Generic SPDT Module
#
# Copyright (C) 2019  Eric Callahan <arksine.code@gmail.com>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import logging


class RunoutHelper:
    def __init__(self, config):
        self.name = config.get_name().split()[-1]
        self.printer = config.get_printer()
        self.reactor = self.printer.get_reactor()
        self.gcode = self.printer.lookup_object('gcode')
        # Read config
        self.runout_pause = config.getboolean('pause_if_disengaged', True)
        if self.runout_pause:
            self.printer.load_object(config, 'pause_resume')
        self.disengage_gcode = self.engage_gcode = None
        gcode_macro = self.printer.load_object(config, 'gcode_macro')
        if self.runout_pause or config.get('disengage_gcode', None) is not None:
            self.disengage_gcode = gcode_macro.load_template(
                config, 'disengage_gcode', '')
        if config.get('engage_gcode', None) is not None:
            self.engage_gcode = gcode_macro.load_template(
                config, 'engage_gcode')
        self.pause_delay = config.getfloat('pause_delay', .5, above=.0)
        self.event_delay = config.getfloat('event_delay', 3., minval=.0)
        # Internal state
        self.min_event_systime = self.reactor.NEVER
        self.filament_present = False
        self.sensor_enabled = True
        # Register commands and event handlers
        self.printer.register_event_handler("klippy:ready", self._handle_ready)
        self.gcode.register_mux_command(
            "QUERY_SPDT", "SENSOR", self.name,
            self.cmd_QUERY_SPDT,
            desc=self.cmd_QUERY_SPDT_help)
        self.gcode.register_mux_command(
            "SET_SPDT", "SENSOR", self.name,
            self.cmd_SET_SPDT,
            desc=self.cmd_SET_SPDT_help)
    def _handle_ready(self):
        self.min_event_systime = self.reactor.monotonic() + 2.
    def _runout_event_handler(self, eventtime):
        # Pausing from inside an event requires that the pause portion
        # of pause_resume execute immediately.
        pause_prefix = ""
        if self.runout_pause:
            pause_resume = self.printer.lookup_object('pause_resume')
            pause_resume.send_pause_command()
            pause_prefix = "PAUSE\n"
            self.printer.get_reactor().pause(eventtime + self.pause_delay)
        self._exec_gcode(pause_prefix, self.disengage_gcode)
    def _insert_event_handler(self, eventtime):
        self._exec_gcode("", self.engage_gcode)
    def _exec_gcode(self, prefix, template):
        try:
            self.gcode.run_script(prefix + template.render() + "\nM400")
        except Exception:
            logging.exception("Script running error")
        self.min_event_systime = self.reactor.monotonic() + self.event_delay
    def note_filament_present(self, eventtime, is_filament_present):
        if is_filament_present == self.filament_present:
            return
        self.filament_present = is_filament_present

        if eventtime < self.min_event_systime or not self.sensor_enabled:
            # do not process during the initialization time, duplicates,
            # during the event delay time, while an event is running, or
            # when the sensor is disabled
            return
        # Determine "printing" status
        now = self.reactor.monotonic()
        idle_timeout = self.printer.lookup_object("idle_timeout")
        is_printing = idle_timeout.get_status(now)["state"] == "Printing"
        # Perform filament action associated with status change (if any)
        if is_filament_present:
            if not is_printing and self.engage_gcode is not None:
                # insert detected
                self.min_event_systime = self.reactor.NEVER
                logging.info(
                    "SPDT %s: engaged @Time %.2f" %
                    (self.name, now))
                self.reactor.register_callback(self._insert_event_handler)
        elif is_printing and self.disengage_gcode is not None:
            # runout detected
            self.min_event_systime = self.reactor.NEVER
            logging.info(
                "SPDT %s: disengaged @Time %.2f" %
                (self.name, now))
            self.reactor.register_callback(self._runout_event_handler)
    def get_status(self, eventtime):
        return {
            "filament_detected": bool(self.filament_present),
            "enabled": bool(self.sensor_enabled)}
    cmd_QUERY_SPDT_help = "Query an SPDT"
    def cmd_QUERY_SPDT(self, gcmd):
        if self.filament_present:
            msg = "SPDT %s: Engaged" % (self.name)
        else:
            msg = "SPDT %s: Disengaged" % (self.name)
        gcmd.respond_info(msg)
    cmd_SET_SPDT_help = "Use SPDT?"
    def cmd_SET_SPDT(self, gcmd):
        self.sensor_enabled = gcmd.get_int("ENABLE", 1)

class SwitchSensor:
    def __init__(self, config):
        printer = config.get_printer()
        buttons = printer.load_object(config, 'buttons')
        switch_pin = config.get('switch_pin')
        buttons.register_debounce_button(switch_pin, self._button_handler
                                         , config)
        self.runout_helper = RunoutHelper(config)
        self.get_status = self.runout_helper.get_status
    def _button_handler(self, eventtime, state):
        self.runout_helper.note_filament_present(eventtime, state)

def load_config_prefix(config):
    return SwitchSensor(config)
