# coding=utf-8
# Copyright 2020 The Edward2 Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# Lint as: python3
"""Benchmark script for the wheel bandit task.
"""

import os
import time

from absl import app
from absl import flags
from experimental.attentive_uncertainty import attention  # local file import
from experimental.attentive_uncertainty.contextual_bandits import offline_contextual_bandits  # local file import
from experimental.attentive_uncertainty.contextual_bandits import utils  # local file import
import numpy as np
import tensorflow.compat.v1 as tf

from deep_contextual_bandits import contextual_bandit  # local file import
from deep_contextual_bandits import neural_linear_sampling  # local file import
from deep_contextual_bandits import posterior_bnn_sampling  # local file import
from deep_contextual_bandits import uniform_sampling  # local file import
from tensorflow.contrib import training as contrib_training

gfile = tf.compat.v1.gfile

tf.compat.v1.enable_eager_execution()

FLAGS = flags.FLAGS
FLAGS.set_default('alsologtostderr', True)
flags.DEFINE_string(
    'logdir',
    '/tmp/bandits/',
    'Base directory to save output.')
flags.DEFINE_integer(
    'num_trials',
    5,
    'Number of trials')
flags.DEFINE_integer(
    'num_contexts',
    2000,
    'Number of contexts')
flags.DEFINE_list('deltas', ['0.5', '0.7', '0.9', '0.95', '0.99'],
                  'delta parameters for wheel bandit instance.')
flags.DEFINE_string(
    'modeldir',
    '/tmp/wheel_bandit/models/multitask',
    'Directory with pretrained models.')
flags.DEFINE_string(
    'datasetdir',
    '/tmp/wheel_bandit/data/',
    'Directory with saved data instances.')
flags.DEFINE_integer(
    'exp_idx',
    0,
    'Experiment idx of full run.')
flags.DEFINE_string(
    'prefix',
    'best_',
    'Prefix of best model ckpts.')
flags.DEFINE_string(
    'suffix',
    '_mse.ckpt',
    'Suffix of best model ckpts.')
flags.DEFINE_list(
    'algo_names',
    ['uniform', 'snp_prior_freeform_offline'],
    'List of algorithms to benchmark.')

context_dim = 2
num_actions = 5


def run_trial(trial_idx, delta, algo_names):
  """Runs a trial of wheel bandit problem instance for a set of algorithms."""

  filename = os.path.join(
      FLAGS.datasetdir,
      str(delta) + '_' + str(trial_idx) + '.npz')
  with gfile.GFile(filename, 'r') as f:
    sampled_vals = np.load(f)
    dataset = sampled_vals['dataset']
    opt_rewards = sampled_vals['opt_rewards']

  x_hidden_size = 100
  x_encoder_sizes = [x_hidden_size]*2

  algos = []
  for algo_name in algo_names:
    if algo_name == 'uniform':
      hparams = contrib_training.HParams(num_actions=num_actions)
      algos.append(uniform_sampling.UniformSampling(algo_name, hparams))
    elif algo_name == 'neurolinear':
      hparams = contrib_training.HParams(
          num_actions=num_actions,
          context_dim=context_dim,
          init_scale=0.3,
          activation=tf.nn.relu,
          output_activation=tf.nn.relu,
          layer_sizes=x_encoder_sizes,
          batch_size=512,
          activate_decay=True,
          initial_lr=0.1,
          max_grad_norm=5.0,
          show_training=False,
          freq_summary=1000,
          buffer_s=-1,
          initial_pulls=2,
          reset_lr=True,
          lr_decay_rate=0.5,
          training_freq=1,
          training_freq_network=20,
          training_epochs=50,
          a0=12,
          b0=30,
          lambda_prior=23)
      algos.append(neural_linear_sampling.NeuralLinearPosteriorSampling(
          algo_name, hparams))
    elif algo_name == 'multitaskgp':
      hparams_gp = contrib_training.HParams(
          num_actions=num_actions,
          num_outputs=num_actions,
          context_dim=context_dim,
          reset_lr=False,
          learn_embeddings=True,
          max_num_points=1000,
          show_training=False,
          freq_summary=1000,
          batch_size=512,
          keep_fixed_after_max_obs=True,
          training_freq=20,
          initial_pulls=2,
          training_epochs=50,
          lr=0.01,
          buffer_s=-1,
          initial_lr=0.001,
          lr_decay_rate=0.0,
          optimizer='RMS',
          task_latent_dim=5,
          activate_decay=False)
      algos.append(posterior_bnn_sampling.PosteriorBNNSampling(
          algo_name, hparams_gp, 'GP'))
    elif algo_name[:3] == 'snp' or algo_name[:3] == 'anp':
      hidden_size = 64
      latent_units = 32
      global_latent_net_sizes = [hidden_size]*2 + [2*latent_units]
      local_latent_net_sizes = [hidden_size]*3 + [2]
      x_y_encoder_sizes = [hidden_size]*3
      heteroskedastic_net_sizes = None
      mean_att_type = attention.laplace_attention
      scale_att_type_1 = attention.laplace_attention
      scale_att_type_2 = attention.laplace_attention
      att_type = 'multihead'
      att_heads = 8
      data_uncertainty = False
      is_anp = False

      config = algo_name.split('_')
      mfile = FLAGS.prefix + config[1] + '_' + config[2] + FLAGS.suffix
      if algo_name[:3] == 'anp':
        mfile = 'anp_' + mfile
        local_latent_net_sizes = [hidden_size]*3 + [2*5]
        is_anp = True
      mpath = os.path.join(FLAGS.modeldir, mfile)

      hparams = contrib_training.HParams(
          num_actions=num_actions,
          context_dim=context_dim,
          init_scale=0.3,
          activation=tf.nn.relu,
          output_activation=tf.nn.relu,
          x_encoder_sizes=x_encoder_sizes,
          x_y_encoder_sizes=x_y_encoder_sizes,
          global_latent_net_sizes=global_latent_net_sizes,
          local_latent_net_sizes=local_latent_net_sizes,
          heteroskedastic_net_sizes=heteroskedastic_net_sizes,
          att_type=att_type,
          att_heads=att_heads,
          mean_att_type=mean_att_type,
          scale_att_type_1=scale_att_type_1,
          scale_att_type_2=scale_att_type_2,
          data_uncertainty=data_uncertainty,
          batch_size=512,
          activate_decay=True,
          initial_lr=0.1,
          max_grad_norm=5.0,
          show_training=False,
          freq_summary=1000,
          buffer_s=-1,
          initial_pulls=2,
          reset_lr=True,
          lr_decay_rate=0.5,
          training_freq=10,
          training_freq_network=20,
          training_epochs=50,
          uncertainty_type='attentive_freeform',
          local_variational=True,
          model_path=mpath,
          is_anp=is_anp)

      if config[1] == 'prior':
        hparams.set_hparam('local_variational', False)

      if config[2] == 'gp':
        hparams.set_hparam('uncertainty_type', 'attentive_gp')

      algos.append(offline_contextual_bandits.OfflineContextualBandits(
          algo_name, hparams))

  t_init = time.time()
  _, h_rewards = contextual_bandit.run_contextual_bandit(
      context_dim,
      num_actions,
      dataset,
      algos,
      num_contexts=FLAGS.num_contexts)  # pytype: disable=wrong-keyword-args
  t_final = time.time()

  return h_rewards, t_final - t_init, opt_rewards[:FLAGS.num_contexts]


def benchmark():
  """Benchmark performance on wheel-bandit."""
  for delta_str in FLAGS.deltas:
    delta = float(delta_str)
    all_regrets, all_times = [], []
    for idx in range(FLAGS.num_trials):
      summary_results = run_trial(idx, delta, FLAGS.algo_names)
      h_rewards, t, opt_rewards = summary_results
      regrets = np.expand_dims(opt_rewards, axis=-1) - h_rewards
      utils.display_results(FLAGS.algo_names,
                            regrets,
                            t,
                            str(delta) + '_' + str(idx))
      all_regrets.append(regrets)
      all_times.append(t)
    all_regrets = np.mean(np.stack(all_regrets), axis=0)
    all_times = np.sum(all_times)
    print('Overall Summary for delta = ', delta)
    utils.display_results(FLAGS.algo_names,
                          all_regrets,
                          all_times,
                          str(delta))


def main(argv):
  del argv
  benchmark()


if __name__ == '__main__':
  app.run(main)
