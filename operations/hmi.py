"""HMI- und Parameter-Operationen."""
from tcg.runtime import CheckFailed


def select_screen(bench, *, screen: str):
    """Wählt einen Bildschirm aus."""
    bench.select_screen(screen)


def expect_screen_text(bench, *, text: str):
    """Prüft den aktuell angezeigten Bildschirmtext."""
    actual = bench.screen_text()
    if actual != text:
        raise CheckFailed(f'Anzeigetext: erwartet {text!r}, aktuell {actual!r}')
    if hasattr(bench, '_log'):
        bench._log('expect_screen_text', expected=text, actual=actual, verdict='PASS')


def write_parameter(bench, *, parameter: str, value):
    """Schreibt einen Parameterwert."""
    bench.write_parameter(parameter, value)


def expect_parameter(bench, *, parameter: str, value):
    """Prüft den aktuellen Parameterwert."""
    actual = bench.read_parameter(parameter)
    if actual != value:
        raise CheckFailed(f'Parameter {parameter}: erwartet {value}, aktuell {actual}')
    if hasattr(bench, '_log'):
        bench._log('expect_parameter', parameter=parameter, expected=str(value), actual=str(actual), verdict='PASS')

