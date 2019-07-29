# -*- coding: utf-8 -*-
'''Test Tacotron2 WaveGlow TTS engine'''

'''will load the WaveGlow model pre-trained on [LJ Speech dataset](https://keithito.com/LJ-Speech-Dataset/)

### Model Description

The Tacotron 2 and WaveGlow model form a text-to-speech system that enables user to synthesise a natural sounding speech from raw transcripts without any additional prosody information. The Tacotron 2 model (also available via torch.hub) produces mel spectrograms from input text using encoder-decoder architecture. WaveGlow is a flow-based model that consumes the mel spectrograms to generate speech.

### Example

In the example below:
- pretrained Tacotron2 and Waveglow models are loaded from torch.hub
- Tacotron2 generates mel spectrogram given tensor represantation of an input text ("Hello world, I missed you")
- Waveglow generates sound given the mel spectrogram
- the output sound is saved in an 'audio.wav' file

To run the example you need some extra python packages installed.
These are needed for preprocessing the text and audio, as well as for display and input / output.

pip install numpy scipy librosa unidecode inflect librosa
'''

import torch
import os
import sys
sys.path.append(os.path.abspath('.'))
sys.dont_write_bytecode = True

import numpy as np
from scipy.io.wavfile import write

try:
  from google.colab import drive
  drive.mount('/content/gdrive')
  root_dir = '/content/gdrive/My Drive'
except ImportError as ex:
  root_dir = os.path.expandvars('$HOME/Desktop/programming/ml/tacotron2-waveflow/')

device = 'cpu'
fp16 = True
waveglow_path = os.path.join(root_dir, 'joc-waveglow-fp16-pyt-20190306')
tacotron2_path = os.path.join(root_dir, 'joc-tacotron2-fp16-pyt-20190306')

# from https://github.com/NVIDIA/DeepLearningExamples/blob/master/PyTorch/SpeechSynthesis/Tacotron2/inference.py
def checkpoint_from_distributed(state_dict):
    """
    Checks whether checkpoint was generated by DistributedDataParallel. DDP
    wraps model in additional "module.", it needs to be unwrapped for single
    GPU inference.
    :param state_dict: model's state dict
    """
    ret = False
    for key, _ in state_dict.items():
        if key.find('module.') != -1:
            ret = True
            break
    return ret


# from https://github.com/NVIDIA/DeepLearningExamples/blob/master/PyTorch/SpeechSynthesis/Tacotron2/inference.py
def unwrap_distributed(state_dict):
    """
    Unwraps model from DistributedDataParallel.
    DDP wraps model in additional "module.", it needs to be removed for single
    GPU inference.
    :param state_dict: model's state dict
    """
    new_state_dict = {}
    for key, value in state_dict.items():
        new_key = key.replace('module.1.', '')
        new_key = new_key.replace('module.', '')
        new_state_dict[new_key] = value
    return new_state_dict


def load_tacotron2 (fp16=fp16):
  '''Constructs a Tacotron 2 model (nn.module with additional infer(input) method).
    For detailed information on model input and output, training recipies, inference and performance
    visit: github.com/NVIDIA/DeepLearningExamples and/or ngc.nvidia.com

    Args (type[, default value]):
        pretrained (bool, True): If True, returns a model pretrained on LJ Speech dataset.
        model_math (str, 'fp32'): returns a model in given precision ('fp32' or 'fp16')
        n_symbols (int, 148): Number of symbols used in a sequence passed to the prenet, see
                              https://github.com/NVIDIA/DeepLearningExamples/blob/master/PyTorch/SpeechSynthesis/Tacotron2/tacotron2/text/symbols.py
        p_attention_dropout (float, 0.1): dropout probability on attention LSTM (1st LSTM layer in decoder)
        p_decoder_dropout (float, 0.1): dropout probability on decoder LSTM (2nd LSTM layer in decoder)
        max_decoder_steps (int, 1000): maximum number of generated mel spectrograms during inference
  '''
  from PyTorch.SpeechSynthesis.Tacotron2.tacotron2 import model as tacotron2
  from PyTorch.SpeechSynthesis.Tacotron2.models import batchnorm_to_float, lstmcell_to_float
  from PyTorch.SpeechSynthesis.Tacotron2.tacotron2.text import text_to_sequence

  ckpt_file = tacotron2_path
  ckpt = torch.load(ckpt_file, map_location=device)
  
  state_dict = ckpt['state_dict']
  if checkpoint_from_distributed(state_dict):
    state_dict = unwrap_distributed(state_dict)
  config = ckpt['config']

  m = tacotron2.Tacotron2(**config)

  if fp16:
    m = batchnorm_to_float(m.half())
    m = lstmcell_to_float(m)

  m.load_state_dict(state_dict)
  m.text_to_sequence = text_to_sequence

  return m


def load_waveglow (fp16=fp16):
  '''Constructs a WaveGlow model (nn.module with additional infer(input) method).
    For detailed information on model input and output, training recipies, inference and performance
    visit: github.com/NVIDIA/DeepLearningExamples and/or ngc.nvidia.com

    Args:
        pretrained (bool): If True, returns a model pretrained on LJ Speech dataset.
        model_math (str, 'fp32'): returns a model in given precision ('fp32' or 'fp16')
  '''
  from PyTorch.SpeechSynthesis.Tacotron2.waveglow import model as waveglow
  from PyTorch.SpeechSynthesis.Tacotron2.models import batchnorm_to_float

  ckpt_file = waveglow_path
  ckpt = torch.load(ckpt_file, map_location=device)
  
  state_dict = ckpt['state_dict']
  if checkpoint_from_distributed(state_dict):
    state_dict = unwrap_distributed(state_dict)
  config = ckpt['config']

  m = waveglow.WaveGlow(**config)

  if fp16:
    m = batchnorm_to_float(m.half())
    for mat in m.convinv:
      mat.float()

  m.load_state_dict(state_dict)

  return m


'''Prepare the waveglow model for inference'''
waveglow = load_waveglow()
if not fp16:
  waveglow = waveglow.remove_weightnorm(waveglow)
waveglow = waveglow.to(device)
waveglow.eval()

'''Load tacotron2'''
tacotron2 = load_tacotron2()
tacotron2 = tacotron2.to(device)
tacotron2.eval()

'''Now, let's make the model say `hello world, I missed you`'''
text = "hello world, I missed you"

'''Now chain pre-processing -> tacotron2 -> waveglow'''
sequence = np.array(tacotron2.text_to_sequence(text, ['english_cleaners']))[None, :]
sequence = torch.from_numpy(sequence).to(device=device, dtype=torch.int64)

# run the models
with torch.no_grad():
    _, mel, _, _ = tacotron2.infer(sequence)
    audio = waveglow.infer(mel)
audio_numpy = audio[0].data.cpu().numpy()
rate = 22050

'''You can write it to a file and listen to it'''
write("audio.wav", rate, audio_numpy)

'''Alternatively, play it right away in a notebook with IPython widgets'''
from IPython.display import Audio
Audio(audio_numpy, rate=rate)