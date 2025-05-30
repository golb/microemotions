import random
import warnings
from functools import partial
from typing import List, Sequence, Tuple

import numpy as np
import pandas as pd
import torch
from torch import nn
from torch.utils.data import Dataset

from .metrics import MultiMetric


class MEData(Dataset):
    """Micro-expression dataloader

    A pytorch dataset for performing data loading in batches and applying
    transformations.
    """

    def __init__(
        self,
        frames: np.ndarray,
        labels: np.ndarray,
        temporal_transform=None,
        spatial_transform=None,
    ):
        self.frames = frames
        self.labels = labels
        self.temporal_transform = temporal_transform
        self.spatial_transform = spatial_transform

    def __len__(self):
        return len(self.frames)

    def __getitem__(self, idx: int):
        sample = self.frames[idx]
        if len(sample.shape) == 4:  # Video
            sample = torch.tensor(sample)
            if self.temporal_transform:
                sample = self.temporal_transform(sample)
            if self.spatial_transform:
                sample = sample.permute(0, 3, 1, 2)  # THWC -> TCHW
                # Assumes that the transform is for video, e.g., pytorchvideo
                sample = self.spatial_transform(sample)
                sample = sample.permute(0, 2, 3, 1)  # TCHW -> THWC
            sample = sample.permute(3, 0, 1, 2)  # THWC -> CTHW

        elif len(sample.shape) == 3:  # Optical flow
            if self.spatial_transform:
                sample = torch.tensor(sample)
                sample = self.spatial_transform(sample)
        else:
            raise NotImplementedError("Only works for len(video.shape) == 3 or 4")

        label = self.labels[idx]
        return sample, label


def reset_weights(m: nn.Module) -> None:
    """Reset weights

    Reset weights of a pytorch module.

    Parameters
    ----------
    m : torch.nn.Module
        A pytorch module with weights.
    """
    for layer in m.children():
        if hasattr(layer, "reset_parameters"):
            layer.reset_parameters()


def set_random_seeds(seed: int = 1) -> None:
    """Sets a random seed

    Sets seed across python, numpy and torch of stochastic functions
    for deterministic output.

    Parameters
    ----------
    seed : int
        Seed value that can be used for reproducing results.
    """
    random.seed(seed)
    torch.manual_seed(seed)
    np.random.seed(seed)
    torch.cuda.manual_seed(seed)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False


class Printer:
    """Prints metrics

    Prints metrics during training and evaluation.
    """

    def __init__(self, config, split_column: str):
        self.cf = config
        self.split_column = split_column

        if isinstance(self.cf.action_units, list) and 'AU' in self.cf.action_units[0]:
            self.label_type = "au"
        elif isinstance(self.cf.action_units, list) and 'emotion' in self.cf.action_units[0]:
            self.label_type = 'emotion'
        else:
            self.label_type = "emotion"

    @staticmethod
    def metric_name(metric) -> str:
        if isinstance(metric, partial):
            metric_name = metric.func.__name__
        else:
            metric_name = metric.__name__
        return metric_name

    def print_test_validation(self, metrics: List[float]) -> None:
        print("Final results\n")
        for i, metric in enumerate(metrics):
            if len(metrics) > 1:
                print(self.metric_name(self.cf.evaluation_fn[i]))
            if isinstance(self.cf.action_units, list) and 'emotion' in self.cf.action_units:
                metric = [metric]
                print(
                    "All AUs: ",
                    list(zip(self.cf.action_units, np.around(np.array(metric) * 100, 2))),
                )
            elif self.cf.action_units != None: # to exclude cases where emotion class is used.
                print(
                    "All AUs: ",
                    list(zip(self.cf.action_units, np.around(np.array(metric) * 100, 2))),
                )
            
            print("Mean: ", np.around(np.mean(metric) * 100, 2))
            print("\n")

    def print_train_test_evaluation(
        self,
        train_metrics: List[float],
        test_metrics: List[float],
        split_name: str,
        n: int,
    ) -> None:
        if self.label_type == "au":
            for i in range(len(train_metrics)):
                if len(train_metrics) > 1:
                    print(self.metric_name(self.cf.evaluation_fn[i]))
                print(
                    f"{self.split_column.capitalize()}: {split_name}, n={n} | "
                    f"train_mean: {np.mean(train_metrics[i]):.4} | "
                    f"test_mean: {np.mean(test_metrics[i]):.4}"
                )
                rounded_metric = np.around(np.array(test_metrics[i]) * 100, 2)
                print(
                    f"Test per AU: {list(zip(self.cf.action_units, rounded_metric))}\n"
                )
        else:
            for i in range(len(train_metrics)):
                if len(train_metrics) > 1:
                    print(self.metric_name(self.cf.evaluation_fn[i]))
                print(
                    f"{self.split_column.capitalize()}: {split_name}, n={n} | "
                    f"train_mean: {np.mean(train_metrics[i]):.4} | "
                    f"test_mean: {np.mean(test_metrics[i]):.4}"
                )

    def print_train_test_validation(
        self, train_metrics: List[float], test_metrics: List[float], epoch: int
    ) -> None:
        print(f"Validating at epoch {epoch + 1}\n")
        print("-" * 80)
        for i in range(len(train_metrics)):
            if len(train_metrics) > 1:
                print(self.metric_name(self.cf.evaluation_fn[i]))
            rounded_metric = np.around(np.array(test_metrics[i]) * 100, 2)
            print(
                f"Training metric mean: {np.mean(train_metrics[i]):>6f}\nTest metric"
                " per AU:"
                f" {list(zip(self.cf.action_units, rounded_metric))}\nTesting"
                f" metric mean: {np.mean(test_metrics[i]):>6f}"
            )
        print("-" * 80)

    @staticmethod
    def list_to_latex(values: list, round_decimals: int = 1) -> str:
        string_list = [str(round(v, round_decimals)) for v in values]
        return " & ".join(string_list)

    def results_to_latex(
        self, outputs_list: List[np.ndarray], df: pd.DataFrame, round_decimals: int = 1
    ) -> None:
        aus = [i for i in self.cf.action_units]
        aus.append("Average")
        dataset_names = df["dataset"].unique().tolist()
        dataset_names.append("Average")
        metrics_aus, metrics_datasets = self.results_to_list(outputs_list, df)
        # Turn list to latex
        for i in range(len(self.cf.evaluation_fn)):
            if len(self.cf.evaluation_fn) > 1:
                print(self.metric_name(self.cf.evaluation_fn[i]))
            metrics_aus_latex = self.list_to_latex(
                metrics_aus[i], round_decimals=round_decimals
            )
            metrics_datasets_latex = self.list_to_latex(
                metrics_datasets[i], round_decimals=round_decimals
            )
            print("AUS:", aus)
            print(metrics_aus_latex)
            print("\nDatasets: ", dataset_names)
            print(metrics_datasets_latex)

    def results_to_list(
        self,
        outputs_list: torch.tensor,
        df: pd.DataFrame,
    ) -> Tuple:
        if not isinstance(self.cf.evaluation_fn, Sequence):
            self.cf.evaluation_fn = [self.cf.evaluation_fn]

        evaluation_fn = MultiMetric(self.cf.evaluation_fn)
        # Per action units
        labels = torch.tensor(np.array(df[self.cf.action_units]))
        metrics_au = evaluation_fn(labels, torch.cat(outputs_list))
        # Multiply by 100 for easier reading
        metrics_au = [[au * 100 for au in metric] for metric in metrics_au]
        # Per split
        metrics_splits = []
        for i, split_name in enumerate(df[self.split_column].unique()):
            df_split = df[df[self.split_column] == split_name]
            labels = torch.tensor(np.array(df_split[self.cf.action_units]))
            metrics_split = np.mean(evaluation_fn(labels, outputs_list[i]), axis=1)
            metrics_splits.append(metrics_split * 100)
        # Transfer to list
        metrics_splits = [
            list(np.array(metrics_splits)[:, i])
            for i in range(len(self.cf.evaluation_fn))
        ]
        # Add average at the end of both
        [metric.append(np.mean(metric)) for metric in metrics_au]
        [metric.append(np.mean(metric)) for metric in metrics_splits]
        return metrics_au, metrics_splits


class ConfigException(Exception):
    """Error in config type"""


class NullScaler:
    """NullScaler that does nothing

    If LossScaler is not used in conjunction with amp autocast
    it is replaced by NullScaler to resume normal training.
    """

    @staticmethod
    def scale(loss):
        return loss

    @staticmethod
    def step(optimizer):
        optimizer.step()

    @staticmethod
    def update():
        pass


def _get_attributes_of_class(cls):
    return [attribute for attribute in dir(cls) if attribute[:2] != "__"]


def _try_if_object_callable(obj):
    """Tests if an object is callable. If not, raise a ConfigException."""
    if obj is None:
        return
    try:
        obj()
    except TypeError as e:
        raise ConfigException(
            "Check that the objects in config are not constructed yet"
            f" for object {obj}. {e}"
        )


def _difference_to_default_config(config, default_config):
    default_attributes = set(_get_attributes_of_class(default_config))
    attributes = set(_get_attributes_of_class(config))
    difference = attributes - default_attributes
    return difference


class ReprMeta(type):
    """Defines __repr__ for class names

    ReprMeta can be used as a metaclass for classes that are used without creating
    an instance of the class. The ReprMeta then provides a __repr__ function for such
    objects, in which the class variables and their corresponding values are returned.
    """

    def __repr__(cls):
        # Query class variables
        variables = [key for key in cls.__dict__ if not key.startswith("__")]
        # Print a dict with class variable and its value
        return str(
            {variable_name: getattr(cls, variable_name) for variable_name in variables}
        )


def validate_config(config, default_config):
    """Validates whether the given objects are in the correct form."""
    object_names = ["criterion", "evaluation_fn", "mixup_fn", "model"]
    for object_name in object_names:
        if isinstance(getattr(config, object_name), list):
            for obj in getattr(config, object_name):
                _try_if_object_callable(obj)
        else:
            _try_if_object_callable(getattr(config, object_name))
    # Validate optimizer seperately
    if "param_groups" in config.optimizer.__dict__:
        raise ConfigException(
            "Check that the optimizer in config is not constructed yet."
        )
    config_difference = _difference_to_default_config(config, default_config)
    if config_difference:
        warnings.warn(
            UserWarning(
                f"Additional attribute(s) found: {config_difference}."
                "See if there are typos."
            )
        )


# A constant dict for handy access to the commonly used action units
# per dataset
dataset_aus = {
    "casme2": ["AU1", "AU2", "AU4", "AU7", "AU12", "AU14", "AU15", "AU17"],
    "casme": ["AU1", "AU4", "AU9", "AU14"],
    "samm": ["AU2", "AU4", "AU7", "AU12"],
    "mmew": ["AU1", "AU2", "AU4", "AU5", "AU7", "AU10", "AU12", "AU14"],
    "fourd": ["AU1", "AU2", "AU4", "AU6", "AU7", "AU12", "AU17", "AU45"],
    "cross": [
        "AU1",
        "AU2",
        "AU4",
        "AU5",
        "AU6",
        "AU7",
        "AU9",
        "AU10",
        "AU12",
        "AU14",
        "AU15",
        "AU17",
    ],
    "emotion": ["emotion"]
}

dataset_emotion = {
    "casme2": ['disgust', 'happiness', 'repression', 'surprise', 'others']
}
