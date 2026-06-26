#!/usr/bin/env python3
"""
Yafti GTK - A simple GTK GUI for running scripts from yafti.yml
"""

import subprocess
import sys, os
import threading
import argparse

import gi
import yaml

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import GLib, Gtk

# Constants
APP_ID = 'io.github.ublue_os.yafti_gtk'
APP_TITLE = 'Bazzite Portal'
DEFAULT_WINDOW_WIDTH = 800
DEFAULT_WINDOW_HEIGHT = 600
STATUS_TIMEOUT_SECONDS = 3
ACTION_DIALOG_WIDTH = 420
DEFAULT_ACCENT = "#a47bea"


def set_widget_margins(widget, top=10, bottom=10, start=10, end=10):
    """Apply consistent margins to a widget."""
    widget.set_margin_top(top)
    widget.set_margin_bottom(bottom)
    widget.set_margin_start(start)
    widget.set_margin_end(end)


def clear_container(container):
    """Remove all children from a container widget."""
    if hasattr(container, 'remove'):
        # For regular containers (Box, etc.)
        while container.get_first_child() is not None:
            container.remove(container.get_first_child())
    elif hasattr(container, 'set_child'):
        # For dialogs and single-child containers
        container.set_child(None)


def show_error_dialog(parent, title, message):
    """Display an error dialog with the given title and message."""
    dialog = Gtk.AlertDialog(
        message=title,
        detail=message,
        buttons=["OK"]
    )
    def _on_dialog_dismissed(dialog, result):
        dialog.choose_finish(result)
    dialog.choose(parent, None, _on_dialog_dismissed)


def initialize_gtk():
    """Initialize GTK and application metadata, then load Adwaita depending on DE."""
    GLib.set_prgname(APP_ID)
    Gtk.init()
    current_desktop = os.environ.get("XDG_CURRENT_DESKTOP","").upper()
    if "KDE" not in current_desktop:
        from gi.repository import Adw
        if Gtk.Settings.get_default().get_property('gtk-application-prefer-dark-theme'):
            Gtk.Settings.get_default().set_property('gtk-application-prefer-dark-theme', False)
        Adw.init()
    try:
        Gtk.Window.set_default_icon_name(APP_ID)
    except Exception as e:
        print(f"Warning: Could not set app icon: {e}")


def build_terminal_command(script):
    """Return the default terminal launcher command."""
    return [
        "xdg-terminal-exec",
        f"--app-id={APP_ID}",
        f"--title={APP_TITLE}",
        "--",
        "bash",
        "--noprofile",
        "--norc",
        "-lc",
        script,
    ]


def build_headless_command(script):
    """Return the non-interactive command used for status checks."""
    return [
        "bash",
        "--noprofile",
        "--norc",
        "-lc",
        script,
    ]


def escape_markup(text):
    """Escape text before using it in a GTK markup label."""
    return GLib.markup_escape_text(text or "")


class YaftiGTK(Gtk.Window):
    def __init__(self, config_file='yafti.yml'):
        super().__init__(title=APP_TITLE)
        self.set_default_size(DEFAULT_WINDOW_WIDTH, DEFAULT_WINDOW_HEIGHT)
        self.active_dialog_state = None
        self.action_widgets = {}  # action_id -> (button)

        # Load YAML configuration
        self.config = self.load_config(config_file)
        self.screens = self.config.get('screens', [])
        self.actions_index = self._build_actions_index()

        # Create main container
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.set_child(vbox)

        # Search bar at the top
        search_entry = Gtk.SearchEntry()
        search_entry.set_placeholder_text(" Search Apps and Actions")
        set_widget_margins(search_entry, 10, 10, 10, 10)
        search_entry.connect("search-changed", self.on_search_changed)
        vbox.append(search_entry)

        # Container to hold the switcher and pages together so they disappear during search
        tabs_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        # Stack for screen pages
        self.screen_stack = Gtk.Stack()
        self.screen_stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        self.screen_stack.set_transition_duration(150)
        self.screen_stack.set_vexpand(True)
        self.screen_stack.set_hexpand(True)

        # Tab switcher
        self.tab_switcher = Gtk.StackSwitcher()
        self.tab_switcher.set_stack(self.screen_stack)
        set_widget_margins(self.tab_switcher, 10, 10, 10, 10)

        # Assemble into container
        tabs_container.append(self.tab_switcher)
        tabs_container.append(self.screen_stack)

        # Add tabs for each screen from YAML
        for screen in self.screens:
            page = self.create_screen_page(screen)
            label = screen.get('title', 'Tab')
            self.screen_stack.add_titled(page, label, label)

        # Stack to switch between container and search results
        self.content_stack = Gtk.Stack()
        self.content_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.content_stack.set_transition_duration(150)

        # Map our tabs view structure to the view name index
        self.content_stack.add_named(tabs_container, "tabs")

        # Search results page
        search_scrolled = Gtk.ScrolledWindow()
        search_scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        results_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        results_box.set_vexpand(True)
        set_widget_margins(results_box, 10, 10, 10, 10)
        self.search_results_box = results_box
        search_scrolled.set_child(results_box)
        self.content_stack.add_named(search_scrolled, "search")

        # Start with tabs visible
        self.content_stack.set_visible_child_name("tabs")

        vbox.append(self.content_stack)

        # Load CSS for highlighting
        GLib.idle_add(self._load_css)

        self.connect("notify::is-active", self.on_window_active_changed)
        focus_controller = Gtk.EventControllerFocus.new()
        focus_controller.connect("enter", self.on_window_focus_in)
        self.add_controller(focus_controller)

    def _load_css(self):
        """Loads CSS to highlight the selected action."""
        def _get_system_accent_color():
            """Fetches the system accent color via XDG Portal."""
            import re
            try:
                out = subprocess.check_output([
                    "gdbus", "call", "-e",
                    "-d", "org.freedesktop.portal.Desktop",
                    "-o", "/org/freedesktop/portal/desktop",
                    "-m", "org.freedesktop.portal.Settings.Read",
                    "'org.freedesktop.appearance'", "'accent-color'"
                ], text=True, stderr=subprocess.DEVNULL)

                r, g, b = map(float, re.findall(r"\d+\.\d+", out)[:3])
                return f"#{int(r * 255):02x}{int(g * 255):02x}{int(b * 255):02x}"
            except Exception:
                return DEFAULT_ACCENT

        accent = _get_system_accent_color()
        css = f"""
        @define-color accent {accent};
        @define-color accent_bg alpha(@accent, 0.3);

        slider,
        .slider {{
            min-height: 8px;
            min-width: 8px;
        }}

        @keyframes flash-animation {{
            0% {{
                border-color: @accent;
            }}
            50% {{
                background-color: @accent_bg;
                border-color: @accent;
            }}
            100% {{
                border-color: @accent;
            }}
        }}

        .highlighted-action {{
            border: 2px solid @accent;
            animation: flash-animation 1000ms ease-in-out 2;
        }}
        """
        provider = Gtk.CssProvider()
        provider.load_from_data(css)
        Gtk.StyleContext.add_provider_for_display(
            self.get_display(),
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    def load_config(self, config_file):
        """Load and parse the YAML configuration file."""
        try:
            with open(config_file, 'r') as f:
                return yaml.safe_load(f) or {}
        except FileNotFoundError:
            show_error_dialog(
                self,
                "Configuration file not found",
                f"Could not find {config_file} in the current directory."
            )
            sys.exit(1)
        except yaml.YAMLError as e:
            show_error_dialog(self, "YAML parsing error", str(e))
            sys.exit(1)

    def create_screen_page(self, screen):
        """Create a page for a screen with all its actions."""
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)

        page_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        set_widget_margins(page_box, 10, 10, 10, 10)

        for action in screen.get('actions', []):
            page_box.append(self.create_action_item(action))

        scrolled.set_child(page_box)
        return scrolled

    def create_action_item(self, action):
        """Create a clickable action item."""
        button = Gtk.Button()
        button.set_hexpand(True)
        button.set_halign(Gtk.Align.FILL)

        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        set_widget_margins(button_box, 8, 8, 8, 8)

        text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)

        title_label = Gtk.Label()
        title_label.set_markup(f"<b>{escape_markup(action.get('title', 'Action'))}</b>")
        title_label.set_xalign(0)
        text_box.append(title_label)

        if action.get('description'):
            desc_label = Gtk.Label(label=action['description'])
            desc_label.set_xalign(0)
            desc_label.set_wrap(True)
            desc_label.set_max_width_chars(120)
            desc_label.add_css_class('dim-label')
            text_box.append(desc_label)

        button_box.append(text_box)
        button.set_child(button_box)
        button.connect("clicked", self.on_action_clicked, action)

        frame = Gtk.Frame()
        frame.set_child(button)

        # Store button for lookup
        action_id = action.get('id')
        if action_id:
            self.action_widgets[action_id] = button

        return frame

    def _build_actions_index(self):
        """Flatten actions for search lookup."""
        index = []
        for screen in self.screens or []:
            for action in screen.get('actions', []):
                index.append(action)
        return index

    def get_action_options(self, action):
        """Return explicit modal options from the config."""
        options = action.get('options')
        if isinstance(options, list) and options:
            return options
        return []

    def action_uses_modal(self, action):
        """Return True when the action should open the management modal."""
        if self.get_action_options(action):
            return True
        return bool((action.get('status_script') or "").strip())

    def on_search_changed(self, entry):
        query = entry.get_text().strip()
        if not query:
            clear_container(self.search_results_box)
            self.content_stack.set_visible_child_name("tabs")
            return

        lowered = query.lower()
        matches = []
        for action in self.actions_index:
            title = action.get('title', '')
            desc = action.get('description', '')
            if lowered in title.lower() or lowered in desc.lower():
                matches.append(item)

        clear_container(self.search_results_box)

        header = Gtk.Label()
        header.set_markup("<b>Search results</b>")
        header.set_xalign(0)
        self.search_results_box.append(header)

        if matches:
            for action in matches:
                self.search_results_box.append(self.create_action_item(item['action']))
        else:
            empty = Gtk.Label(label="No matches found")
            empty.set_xalign(0)
            self.search_results_box.append(empty)

        self.search_results_box.set_visible(True)
        self.content_stack.set_visible_child_name("search")

    def on_action_clicked(self, _button, action):
        """Open a management modal or run the action directly."""
        if not self.action_uses_modal(action):
            script = (action.get('script') or "").strip()
            if not script:
                return

            error_message = self.launch_terminal(script)
            if isinstance(error_message, subprocess.Popen):
                return

            show_error_dialog(
                self,
                "No terminal available",
                f"{error_message}\n\nCould not open a terminal automatically.\nYou can also run the following command manually:\n\n{script}"
            )
            return

        dialog = Gtk.Dialog(title=action.get('title', 'Action'), transient_for=self)
        dialog.set_modal(True)
        dialog.set_destroy_with_parent(True)
        dialog.set_default_size(ACTION_DIALOG_WIDTH, -1)
        dialog.set_resizable(False)

        state = {
            'action': action,
            'dialog': dialog,
            'dirty': False,
            'loading': False,
            'closed': False,
            'request_id': 0,
            'status_token': None,
            'status_timed_out': False,
        }
        self.active_dialog_state = state

        dialog.connect("destroy", self.on_dialog_destroy, state)
        dialog.connect("notify::is-active", self.on_dialog_active_changed, state)
        focus_controller = Gtk.EventControllerFocus.new()
        focus_controller.connect("enter", self.on_dialog_focus_in, state)
        dialog.add_controller(focus_controller)

        if (action.get('status_script') or "").strip():
            self.refresh_action_dialog(state)
        else:
            self.build_action_dialog_content(state, None)

    def on_dialog_destroy(self, _dialog, state):
        """Clear the active dialog reference when the modal closes."""
        state['closed'] = True
        if self.active_dialog_state is state:
            self.active_dialog_state = None

    def on_window_active_changed(self, window, _pspec):
        """Refresh the active dialog when the portal window becomes active."""
        if window.get_property("is-active"):
            GLib.idle_add(self.refresh_active_dialog_if_needed)

    def on_dialog_active_changed(self, dialog, _pspec, state):
        """Refresh the dialog when it becomes active again."""
        if dialog.get_property("is-active"):
            self.refresh_dialog_if_needed(state)

    def on_window_focus_in(self, _controller):
        """Refresh the active dialog on focus return when needed."""
        GLib.idle_add(self.refresh_active_dialog_if_needed)
        return False

    def on_dialog_focus_in(self, _controller, state):
        """Refresh the focused dialog after a launched action when needed."""
        GLib.idle_add(self.refresh_dialog_if_needed, state)
        return False

    def refresh_active_dialog_if_needed(self):
        """Refresh the active dialog if a launched action may have changed status."""
        self.refresh_dialog_if_needed(self.active_dialog_state)

    def refresh_dialog_if_needed(self, state):
        """Refresh a dialog when its status is dirty."""
        if self.should_refresh_dialog(state):
            self.refresh_action_dialog(state, background_only=True)

    def should_refresh_dialog(self, state):
        """Return True when a dialog should refresh its status on focus return."""
        if not state or state.get('closed'):
            return False
        if self.active_dialog_state is not state:
            return False
        if state.get('loading'):
            return False
        return state.get('dirty', False)

    def refresh_action_dialog(self, state, background_only=False):
        """Show the loading state and rerun the dialog status check."""
        if not state or state.get('closed'):
            return

        action = state['action']
        status_script = (action.get('status_script') or "").strip()
        if not status_script:
            self.build_action_dialog_content(state, None)
            return

        state['dirty'] = False
        state['request_id'] += 1
        request_id = state['request_id']
        if not background_only:
            self.build_action_dialog_loading(state)

        thread = threading.Thread(
            target=self.run_status_check,
            args=(state, request_id, status_script),
            daemon=True,
        )
        thread.start()

    def build_action_dialog_loading(self, state):
        """Render the loading-only modal view."""
        dialog = state['dialog']
        clear_container(dialog)
        state['loading'] = True

        loading_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        loading_box.set_halign(Gtk.Align.CENTER)
        loading_box.set_valign(Gtk.Align.CENTER)
        set_widget_margins(loading_box, 24, 24, 24, 24)

        spinner = Gtk.Spinner()
        spinner.start()
        loading_box.append(spinner)

        label = Gtk.Label(label="Loading...")
        loading_box.append(label)

        dialog.set_child(loading_box)
        dialog.set_visible(True)

    def run_status_check(self, state, request_id, status_script, background_only=False):
        """Run the modal status check in the background."""
        status_token = "unknown"
        status_timed_out = False

        try:
            result = subprocess.run(
                build_headless_command(status_script),
                capture_output=True,
                text=True,
                timeout=STATUS_TIMEOUT_SECONDS,
                check=False,
            )

            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    token = line.strip()
                    if token:
                        status_token = token
                        break
        except subprocess.TimeoutExpired:
            status_timed_out = True
        except Exception:
            status_token = "unknown"

        GLib.idle_add(
            self.finish_status_check,
            state,
            request_id,
            status_token,
            status_timed_out,
            background_only,
        )

    def finish_status_check(self, state, request_id, status_token, status_timed_out, background_only=False):
        """Update the dialog once the status check completes."""
        if not state or state.get('closed'):
            return False
        if self.active_dialog_state is not state:
            return False
        if state.get('request_id') != request_id:
            return False

        if background_only and not state.get('loading'):
            self.update_dialog_highlights(state, status_token)
        else:
            self.build_action_dialog_content(state, status_token, status_timed_out)
        return False

    def update_dialog_highlights(self, state, status_token):
        """Updates button highlights in-place without rebuilding the dialog layout."""
        state['status_token'] = status_token
        for button, option in state.get('option_buttons', []):
            if self.option_is_highlighted(option, status_token):
                button.add_css_class("suggested-action")
            else:
                button.remove_css_class("suggested-action")

    def build_action_dialog_content(self, state, status_token, status_timed_out=False):
        """Render the full action dialog after status is known."""
        dialog = state['dialog']
        action = state['action']
        clear_container(dialog)

        state['loading'] = False
        state['status_token'] = status_token
        state['status_timed_out'] = status_timed_out

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        set_widget_margins(root, 16, 16, 16, 16)

        title_label = Gtk.Label()
        title_label.set_markup(f"<big><b>{escape_markup(action.get('title', 'Action'))}</b></big>")
        title_label.set_xalign(0)
        root.append(title_label)

        description = action.get('description')
        if description:
            desc_label = Gtk.Label(label=description)
            desc_label.set_xalign(0)
            desc_label.set_wrap(True)
            desc_label.add_css_class('dim-label')
            root.append(desc_label)

        if status_timed_out:
            status_label = Gtk.Label()
            status_label.set_markup(
                "<span foreground='red'><b>Status check timed out. You can still run the action.</b></span>"
            )
            status_label.set_xalign(0)
            status_label.set_wrap(True)
            root.append(status_label)

        actions_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        active_button = None
        for option in self.get_action_options(action):
            option_button = Gtk.Button(label=option.get('label', 'Run'))
            option_button.set_hexpand(True)
            option_button.set_halign(Gtk.Align.FILL)

            if self.option_is_highlighted(option, status_token):
                option_button.add_css_class("suggested-action")
                active_button = option_button

            option_button.connect("clicked", self.on_option_clicked, state, option)
            actions_box.append(option_button)

        root.append(actions_box)

        close_button = Gtk.Button(label="Close")
        close_button.connect("clicked", lambda _button: dialog.destroy())
        root.append(close_button)

        dialog.set_child(root)
        dialog.set_visible(True)

        if active_button:
            dialog.set_focus(active_button)

    def option_is_highlighted(self, option, status_token):
        """Return True when the option ID matches the current status token."""
        if not status_token or status_token == "unknown":
            return False

        option_id = (option.get('id') or "").strip().lower()
        current_status = status_token.strip().lower()
        return bool(option_id) and option_id == current_status

    def on_option_clicked(self, _button, state, option):
        """Launch the selected modal action in a terminal."""
        script = (option.get('script') or "").strip()
        if not script:
            return

        result = self.launch_terminal(script)

        if isinstance(result, subprocess.Popen):
            if (state['action'].get('status_script') or "").strip():
                state['dirty'] = True

                # Create a thread to wait for the terminal to close, then update UI
                def wait_and_refresh():
                    result.wait()
                    GLib.idle_add(self.refresh_action_dialog, state, True)

                threading.Thread(target=wait_and_refresh, daemon=True).start()
            return

        show_error_dialog(
            self,
            "No terminal available",
            f"{result}\n\nCould not open a terminal automatically.\nYou can also run the following command manually:\n\n{script}"
        )

    def launch_terminal(self, script):
        """Attempt to run a command in a terminal. Returns None on success."""
        try:
            process = subprocess.Popen(build_terminal_command(script))
            return process
        except FileNotFoundError:
            return "The default terminal launcher (xdg-terminal-exec) was not found."
        except Exception as e:
            return f"Terminal launch failed: {e}"

    def _get_page_for_widget(self, widget):
        """Gets the page number of the widget to switch to. Returns None on fail."""
        current = widget
        while current is not None:
            parent = current.get_parent()
            # Parent is screen stack, current is stack of screens
            if parent == self.screen_stack:
                page_name = self.screen_stack.get_page(current).get_name()
                return page_name
            current = parent
        return None

    def _apply_highlight(self, button):
        """Scroll and applies highlight"""
        scrolled = button.get_ancestor(Gtk.ScrolledWindow)
        if scrolled:
            try:
                scrolled.scroll_to_child(button, None)
            except AttributeError:
                pass
        button.add_css_class("highlighted-action")
        if button.get_mapped():
            self.set_focus(button)

    def highlight_action(self, action_id):
        if action_id not in self.action_widgets:
            return

        button = self.action_widgets[action_id]
        page_name = self._get_page_for_widget(button)
        self.content_stack.set_visible_child_name("tabs")
        self.screen_stack.set_visible_child_name(page_name)
        GLib.timeout_add(250, lambda: [self._apply_highlight(button), False][1])

def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Bazzite Portal")
    parser.add_argument("CONFIG_FILE", help="Path to the yafti.yml configuration file")
    parser.add_argument("--action-id", help="ID of the action to highlight", default=None)
    args = parser.parse_args()

    # Initialize GTK before creating the window.
    initialize_gtk()

    loop = GLib.MainLoop()

    # Create and show window
    win = YaftiGTK(args.CONFIG_FILE)
    win.connect("close-request", lambda *_: loop.quit())
    win.set_visible(True)

    # If an action ID was provided, highlight it after window is shown
    if args.action_id:
        GLib.idle_add(win.highlight_action, args.action_id)

    loop.run()


if __name__ == '__main__':
    main()
