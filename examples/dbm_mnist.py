#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Train 2-layer Bernoulli DBM on MNIST dataset.
Hyper-parameters are similar to those in MATLAB code [1].
Some of them were changed for more efficient computation on GPUs,
another ones to obtain more stable learning (lesser number of "died" units etc.)

RBM #2 trained with increasing k in CD-k and decreasing learning rate.

Links
-----
[1] http://www.cs.toronto.edu/~rsalakhu/DBM.html
"""
print __doc__


import os
import argparse
import numpy as np

import env
from hdm.dbm import DBM
from hdm.rbm import BernoulliRBM
from hdm.utils import RNG
from hdm.utils.dataset import load_mnist


def main():
    # training settings
    parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('--gpu', type=str, default='0', metavar='ID',
                        help="ID of the GPU to train on (or '' to train on CPU)")
    parser.add_argument('--n-train', type=int, default=59000, metavar='N',
                        help='number of training examples')
    parser.add_argument('--n-val', type=int, default=1000, metavar='N',
                        help='number of validation examples')

    # common
    parser.add_argument('--n-hiddens', type=int, default=[512, 1024], metavar='N', nargs='+',
                        help='numbers of hidden units')
    parser.add_argument('--epochs', type=int, default=[64, 120, 500], metavar='N', nargs='+',
                        help='number of epochs to train')
    parser.add_argument('--batch-size', type=int, default=[48, 48, 100], metavar='B', nargs='+',
                        help='input batch size for training, `--n-train` and `--n-val`' + \
                             'must be divisible by this number (for DBM)')
    parser.add_argument('--increase-n-gibbs-steps-every', type=int, default=20, metavar='I',
                        help='increase number of Gibbs steps every specified number of epochs for RBM #2')

    # dirpaths
    parser.add_argument('--rbm1-dirpath', type=str, default='../models/dbm_mnist_rbm1/', metavar='DIRPATH',
                        help='directory path to save RBM #1')
    parser.add_argument('--rbm2-dirpath', type=str, default='../models/dbm_mnist_rbm2/', metavar='DIRPATH',
                        help='directory path to save RBM #2')
    parser.add_argument('--dbm-dirpath', type=str, default='../models/dbm_mnist/', metavar='DIRPATH',
                        help='directory path to save DBM')

    parser.add_argument('--load-rbm1', type=str, default=None, metavar='DIRPATH',
                        help='directory path to load trained RBM #1')
    parser.add_argument('--load-rbm2', type=str, default=None, metavar='DIRPATH',
                        help='directory path to load trained RBM #2')
    parser.add_argument('--load-dbm', type=str, default=None, metavar='DIRPATH',
                        help='directory path to load trained DBM')

    # DBM-related
    parser.add_argument('--n-particles', type=int, default=100, metavar='M',
                        help='number of persistent Markov chains')
    parser.add_argument('--n-gibbs-steps', type=int, default=5, metavar='N',
                        help='number of Gibbs steps for PCD')
    parser.add_argument('--max-mf-updates', type=int, default=50, metavar='N',
                        help='maximum number of mean-field updates per weight update')
    parser.add_argument('--mf-tol', type=float, default=1e-7, metavar='TOL',
                        help='mean-field tolerance')
    parser.add_argument('--lr', type=float, default=5e-4, metavar='LR',
                        help='initial learning rate')
    parser.add_argument('--l2', type=float, default=1e-7, metavar='L2',
                        help='L2 weight decay coefficient')
    parser.add_argument('--max-norm', type=float, default=8., metavar='C',
                        help='maximum norm constraint')
    parser.add_argument('--sparsity-target', type=float, default=[0.2, 0.1], metavar='T', nargs='+',
                        help='desired probability of hidden activation')
    parser.add_argument('--sparsity-cost', type=float, default=[1e-3, 1e-3], metavar='C', nargs='+',
                        help='controls the amount of sparsity penalty')
    parser.add_argument('--sparsity-damping', type=float, default=0.9, metavar='D',
                        help='decay rate for hidden activations probs')

    args = parser.parse_args()
    os.environ['CUDA_VISIBLE_DEVICES'] = args.gpu
    if len(args.epochs) == 1: args.epochs *= 3
    if len(args.batch_size) == 1: args.batch_size *= 3
    if len(args.sparsity_target) == 1: args.sparsity_target *= 2
    if len(args.sparsity_cost) == 1: args.sparsity_cost *= 2
    if args.load_rbm1 == '': args.load_rbm1 = args.rbm1_dirpath
    if args.load_rbm2 == '': args.load_rbm2 = args.rbm2_dirpath
    if args.load_dbm == '': args.load_dbm = args.dbm_dirpath

    # prepare data
    X, _ = load_mnist(mode='train', path='../data/')
    X /= 255.
    RNG(seed=42).shuffle(X)
    X_train = X[:args.n_train]
    X_val = X[-args.n_val:]
    X = np.concatenate((X_train, X_val))

    # pre-train RBM #1
    if args.load_rbm1:
        print "\nLoading RBM #1 ...\n\n"
        rbm1 = BernoulliRBM.load_model(args.load_rbm1)
    else:
        print "\nTraining RBM #1 ...\n\n"
        rbm1 = BernoulliRBM(n_visible=784,
                            n_hidden=args.n_hiddens[0],
                            W_init=0.001,
                            vb_init=0.,
                            hb_init=0.,
                            n_gibbs_steps=1,
                            learning_rate=0.05,
                            momentum=[0.5] * 5 + [0.9],
                            max_epoch=args.epochs[0],
                            batch_size=args.batch_size[0],
                            l2=1e-3,
                            sample_h_states=True,
                            sample_v_states=True,
                            sparsity_cost=0.,
                            dbm_first=True,  # !!!
                            metrics_config=dict(
                                msre=True,
                                pll=True,
                                train_metrics_every_iter=500,
                            ),
                            verbose=True,
                            random_seed=1337,
                            tf_dtype='float32',
                            tf_saver_params=dict(max_to_keep=1),
                            model_path=args.rbm1_dirpath)
        rbm1.fit(X)

    # freeze RBM #1 and extract features Q = P_{RBM1}(h|v=X)
    Z = None
    if not args.load_rbm2 or not args.load_dbm:
        print "\nExtracting features from RBM #1 ...\n\n"
        Z = rbm1.transform(X)
        print Z.shape

    # pre-train RBM #2
    if args.load_rbm2:
        print "\nLoading RBM #2 ...\n\n"
        rbm2 = BernoulliRBM.load_model(args.load_rbm2)
    else:
        print "\nTraining RBM #2 ...\n\n"
        rbm2_learning_rate = 0.01
        rbm2_config = dict(
            n_visible=args.n_hiddens[0],
            n_hidden=args.n_hiddens[1],
            W_init=0.005,
            vb_init=0.,
            hb_init=0.,
            n_gibbs_steps=1,
            learning_rate=rbm2_learning_rate,
            momentum=[0.5] * 5 + [0.9],
            max_epoch=args.increase_n_gibbs_steps_every,
            batch_size=args.batch_size[1],
            l2=2e-4,
            sample_h_states=True,
            sample_v_states=True,
            sparsity_cost=0.,
            dbm_last=True,  # !!!
            metrics_config=dict(
                msre=True,
                pll=True,
                train_metrics_every_iter=2000,
            ),
            verbose=True,
            display_filters=False,
            random_seed=1111,
            tf_dtype='float32',
            tf_saver_params=dict(max_to_keep=1),
            model_path=args.rbm2_dirpath
        )
        max_epoch = args.increase_n_gibbs_steps_every
        rbm2 = BernoulliRBM(**rbm2_config)
        rbm2.fit(Z)
        rbm2_config['momentum'] = 0.9
        while max_epoch < args.epochs[1]:
            max_epoch += args.increase_n_gibbs_steps_every
            max_epoch = min(max_epoch, args.epochs[1])
            rbm2_config['max_epoch'] = max_epoch
            rbm2_config['n_gibbs_steps'] += 1
            rbm2_config['learning_rate'] = rbm2_learning_rate / float(rbm2_config['n_gibbs_steps'])

            print "\nNumber of Gibbs steps = {0}, learning rate = {1:.4f} ...\n\n".\
                  format(rbm2_config['n_gibbs_steps'], rbm2_config['learning_rate'])

            rbm2_new = BernoulliRBM(**rbm2_config)
            rbm2_new.init_from(rbm2)
            rbm2 = rbm2_new
            rbm2.fit(Z)

    # jointly train DBM
    if args.load_dbm:
        print "\nLoading DBM ...\n\n"
        dbm = DBM.load_model(args.load_dbm)
        dbm.load_rbms([rbm1, rbm2])  # !!!
    else:
        # freeze RBM #2 and extract features G = P_{RBM2}(h|v=Q)
        print "\nExtracting features from RBM #2 ...\n\n"
        Q = rbm2.transform(Z)
        print Q.shape

        print "\nTraining DBM ...\n\n"
        dbm = DBM(rbms=[rbm1, rbm2],
                  n_particles=args.n_particles,
                  v_particle_init=X[:args.n_particles].copy(),
                  h_particles_init=(Z[:args.n_particles].copy(),
                                    Q[:args.n_particles].copy()),
                  n_gibbs_steps=args.n_gibbs_steps,
                  max_mf_updates=args.max_mf_updates,
                  mf_tol=args.mf_tol,
                  learning_rate=np.geomspace(args.lr, 1e-5, 200),
                  momentum=np.geomspace(0.5, 0.9, 8),
                  max_epoch=args.epochs[2],
                  batch_size=args.batch_size[2],
                  l2=args.l2,
                  max_norm=args.max_norm,
                  sample_v_states=True,
                  sample_h_states=(True, True),
                  sparsity_targets=args.sparsity_target,
                  sparsity_costs=args.sparsity_cost,
                  sparsity_damping=args.sparsity_damping,
                  train_metrics_every_iter=500,
                  val_metrics_every_epoch=2,
                  random_seed=2222,
                  verbose=True,
                  tf_dtype='float32',
                  save_after_each_epoch=True,
                  tf_saver_params=dict(max_to_keep=1),
                  model_path=args.dbm_dirpath)
        dbm.fit(X_train, X_val)

    def f(n_b):
        log_Z = dbm.log_Z(n_betas=n_b)
        mean = log_Z.mean()
        std = log_Z.std()
        print "{0} -> {1:.2f} +- {2:.2f}".format(n_b, mean, std)
        return mean

    # f(100)
    # log_Z = f(1000)

    # print dbm.log_proba(X_val, log_Z=355.87)
    # print dbm.log_proba(X_val, log_Z=log_Z).mean()

    # g_i = p(h_{L-1}|v=x_i)
    # G = dbm.transform(X)
    # print G.shape, G.min(), G.max(), G.mean(), G.sum()

    V = dbm.sample_v(n_gibbs_steps=10)
    print V.shape, V.min(), V.max(), V.mean(), V.sum()
    from hdm.utils import plot_matrices
    import matplotlib.pyplot as plt
    fig = plt.figure(figsize=(10, 10))
    plot_matrices(V, shape=(28, 28), imshow_params={'cmap': plt.cm.gray})
    plt.show()


if __name__ == '__main__':
    main()