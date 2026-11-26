"""Starts the app. If anything goes wrong, the error is shown on screen
(so it can be photographed) instead of the app silently closing."""
import traceback


def show_error(text):
    from kivy.app import App
    from kivy.core.clipboard import Clipboard
    from kivy.uix.boxlayout import BoxLayout
    from kivy.uix.button import Button
    from kivy.uix.label import Label
    from kivy.uix.scrollview import ScrollView

    class ErrorApp(App):
        def build(self):
            root = BoxLayout(orientation="vertical", padding=10, spacing=8)
            root.add_widget(Label(
                text="The Pod crashed. Take a photo of this screen.",
                size_hint_y=None, height=40, bold=True))
            scroll = ScrollView()
            body = Label(text=text, font_size="11sp", size_hint_y=None,
                         halign="left", valign="top", markup=False)
            body.bind(width=lambda w, v: setattr(w, "text_size", (v, None)))
            body.bind(texture_size=lambda w, s: setattr(w, "height", s[1]))
            scroll.add_widget(body)
            root.add_widget(scroll)
            copy = Button(text="Copy error text", size_hint_y=None, height=48)
            copy.bind(on_release=lambda *_: Clipboard.copy(text))
            root.add_widget(copy)
            return root

    ErrorApp().run()


try:
    from podapp import PodInventoryApp

    PodInventoryApp().run()
except Exception:
    show_error(traceback.format_exc())
