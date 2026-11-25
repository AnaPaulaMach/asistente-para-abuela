"""Tareas de fondo (asyncio) que no se pierden ni fallan en silencio.

asyncio.create_task solo guarda una referencia débil: una tarea que nadie
guarda puede desaparecer, y si falla, el error no se ve en ningún lado.
lanzar() la guarda hasta que termina y anota en el registro si falló.
"""
import asyncio

_vivas = set()


def lanzar(corrutina, nombre=""):
    tarea = asyncio.create_task(corrutina, name=nombre or None)
    _vivas.add(tarea)
    tarea.add_done_callback(_termino)
    return tarea


def _termino(tarea):
    _vivas.discard(tarea)
    if not tarea.cancelled() and tarea.exception() is not None:
        print(f"⚠️  La tarea «{tarea.get_name()}» se cayó: {tarea.exception()!r}", flush=True)
