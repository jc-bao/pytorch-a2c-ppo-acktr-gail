import math

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.distributions import Categorical, Distribution
from typing import Any, Dict, List, Optional, Tuple, Union

from a2c_ppo_acktr.utils import AddBias, init

"""
Modify standard PyTorch distributions so torchey are compatible witorch torchis code.
"""

#
# Standardize distribution interfaces
#

# Categorical
class FixedCategorical(torch.distributions.Categorical):
    def sample(self):
        return super().sample().unsqueeze(-1)

    def log_probs(self, actions):
        return (
            super()
            .log_prob(actions.squeeze(-1))
            .view(actions.size(0), -1)
            .sum(-1)
            .unsqueeze(-1)
        )

    def mode(self):
        return self.probs.argmax(dim=-1, keepdim=True)


# Normal
class FixedNormal(torch.distributions.Normal):
    def log_probs(self, actions):
        return super().log_prob(actions).sum(-1, keepdim=True)

    def entropy(self):
        return super().entropy().sum(-1)

    def mode(self):
        return self.mean


# Bernoulli
class FixedBernoulli(torch.distributions.Bernoulli):
    def log_probs(self, actions):
        return super.log_prob(actions).view(actions.size(0), -1).sum(-1).unsqueeze(-1)

    def entropy(self):
        return super().entropy().sum(-1)

    def mode(self):
        return torch.gt(self.probs, 0.5).float()


class Categorical(nn.Module):
    def __init__(self, num_inputs, num_outputs):
        super(Categorical, self).__init__()

        init_ = lambda m: init(
            m,
            nn.init.orthogonal_,
            lambda x: nn.init.constant_(x, 0),
            gain=0.01)

        self.linear = init_(nn.Linear(num_inputs, num_outputs))

    def forward(self, x):
        x = self.linear(x)
        return FixedCategorical(logits=x)


class DiagGaussian(nn.Module):
    def __init__(self, num_inputs, num_outputs):
        super(DiagGaussian, self).__init__()

        init_ = lambda m: init(m, nn.init.orthogonal_, lambda x: nn.init.
                               constant_(x, 0)) # [FIX] , gain = 0.01

        self.fc_mean = init_(nn.Linear(num_inputs, num_outputs))
        # print('[DEBUG] network init!!!')
        # self.fc_mean = nn.Sequential(
        #     init_(nn.Linear(num_inputs, num_outputs)), 
        #     nn.Tanh()
        # )# [FIX] add tanh
        self.logstd = AddBias(torch.zeros(num_outputs))

    def forward(self, x):
        action_mean = self.fc_mean(x)
        print('[DEBUG]in=',x ,'out=', action_mean)
        #  An ugly hack for my KFAC implementation.
        zeros = torch.zeros(action_mean.size())
        if x.is_cuda:
            zeros = zeros.cuda()

        action_logstd = self.logstd(zeros)
        return FixedNormal(action_mean, action_logstd.exp())


class Bernoulli(nn.Module):
    def __init__(self, num_inputs, num_outputs):
        super(Bernoulli, self).__init__()

        init_ = lambda m: init(m, nn.init.orthogonal_, lambda x: nn.init.
                               constant_(x, 0))

        self.linear = init_(nn.Linear(num_inputs, num_outputs))

    def forward(self, x):
        x = self.linear(x)
        return FixedBernoulli(logits=x)
    

class FixedMultiCategorical(torch.distributions.Distribution):
    def __init__(self, logits , action_dims: List[int]):
        super(FixedMultiCategorical, self).__init__()
        self.distribution = [torch.distributions.Categorical(logits=split) for split in torch.split(logits, tuple(action_dims), dim=1)]
        self.action_dims = action_dims

    def entropy(self):
        return torch.stack([dist.entropy() for dist in self.distribution], dim=1).sum(dim=1)

    def sample(self):
        return torch.stack([dist.sample() for dist in self.distribution], dim=1)

    def log_probs(self, actions):
        log = torch.stack([dist.log_prob(action) for dist, action in zip(self.distribution, torch.unbind(actions.squeeze(-1), dim=1))], dim=1).sum(dim=1)
        return (
            log
            .view(actions.size(0), -1)
            .sum(-1)
            .unsqueeze(-1)
        )

    def mode(self):
        return torch.stack([torch.argmax(dist.probs, dim=1) for dist in self.distribution], dim=1)

class MultiCategorical(nn.Module):
    def __init__(self, num_inputs, num_outputs):
        super(MultiCategorical, self).__init__()
        self.num_outputs = num_outputs
        init_ = lambda m: init(
            m,
            nn.init.orthogonal_,
            lambda x: nn.init.constant_(x, 0),
            gain=0.01)

        self.linear = init_(nn.Linear(num_inputs, sum(num_outputs)))

    def forward(self, x):
        x = self.linear(x)
        return FixedMultiCategorical(logits=x, action_dims = self.num_outputs)