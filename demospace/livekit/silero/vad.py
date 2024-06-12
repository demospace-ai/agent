import torch
from livekit.plugins import silero


class VAD(silero.VAD):
  def __init__(
    self,
    *,
    min_silence_duration: float = 0.8,
    use_onnx: bool = True,
  ) -> None:
    self._min_silence_duration = min_silence_duration

    self._model, _ = torch.hub.load(
      repo_or_dir="snakers4/silero-vad",
      model="silero_vad",
      onnx=use_onnx,
      trust_repo=True,
    )

  def stream(
    self,
    *,
    min_speaking_duration: float = 0.2,
    min_silence_duration: float | None = None,
    padding_duration: float = 0.1,
    sample_rate: int = 16000,
    max_buffered_speech: float = 45.0,
    threshold: float = 0.2,
  ) -> silero.VADStream:
    if min_silence_duration is None:
      min_silence_duration = self._min_silence_duration

    return silero.VADStream(
      self._model,
      min_speaking_duration=min_speaking_duration,
      min_silence_duration=min_silence_duration,
      padding_duration=padding_duration,
      sample_rate=sample_rate,
      max_buffered_speech=max_buffered_speech,
      threshold=threshold,
    )
