import os, sys
from pprint import pp

from functools import partial
import asyncio
from copy import deepcopy
from typing import Union, Optional
from concurrent import futures
import os, sys
from typing import *
from loguru import logger
import time
from munch import Munch
import argparse
import torch
import json

# logger = logger.opt(colors=True)
    
# import torch
import commune
# commune.utils
from torch import nn
# commune.new_event_loop()
from commune.metric import MetricMap
import bittensor
from commune.utils.tokenizer import get_translation_map, translate_logits_to_probs_std, \
    translate_special_token_text, pad_offsets, topk_token_phrases, compact_topk_token_phrases, \
        encode_topk, decode_topk
 
"""
Examples 



"""
class Model( nn.Module, commune.Module):

    def __init__(self,
                # model_name: str="EleutherAI/gpt-j-6B",
                tag :str = None,
                metrics: Dict[str, 'Metric'] = None,
                stats: Dict[str, 'Metric'] = None,
                device: str='cuda',
                load: bool = False,
                finetune: bool = None,
                
                **kwargs
                ):
        
        
        
        
        nn.Module.__init__(self)
        
        self.tag = tag 
        self.metrics = metrics if metrics != None else MetricMap(metrics=metrics)
        self.stats = stats if stats != None else {'tag': self.tag}
        
        
    def set_metrics(self, metrics: Dict[str, 'Metric']  , from_dict:bool  = True) -> None:
        if not hasattr(self, 'metrics'):
            if from_dict:
                self.metrics = MetricMap.from_dict(metrics)
            else:
                self.metrics = MetricMap(metrics=metrics)
        
        for key, metric in metrics.items():
            self.metrics[key] = metric
                
          
    def set_metric(self, key:str, value:float, **kwargs):
        return self.metrics.set_metric(key=key, value=value, **kwargs)
        
    def get_metric(self, key:str, value:float, **kwargs) -> float:
        return self.metrics.get_metric(key=key, value=value, **kwargs)
    
    def get_metrics(self)-> Dict:
        return self.metrics.get_metrics()
        

    def set_optimizer(self, optimizer:Union[Dict, 'Optimizer']=None) -> None:
        
        if isinstance(optimizer, dict):
            module_path = optimizer.pop('module', 'torch.optim.Adam')
            assert module_name != None, f'Please specify a valid optimizer ex: torch.optim.Adam'
            optimizer_class = self.import_object(module_path) 
            kwargs = optimizer.get('params', optimizer.get('kwargs', optimizer))
                
        elif optimizer == None:
            optimizer_class = torch.optim.Adam
            kwargs = {'lr': 0.00002}
            
        
        else:
            raise NotImplementedError(optimizer)
        
        self.optimizer = optimizer_class(self.parameters(), **kwargs)



    def forward(self,  **kwargs) -> Union[Dict, torch.Tensor]:
        # import ipdb; ipdb.set_trace()
        no_grad = kwargs.pop('no_grad', True)
        autocast = kwargs.pop('autocast', True)
        #should the model learn from the input in this forward pass
        learn = kwargs['learn'] = kwargs.get('learn', True)

        if learn == True:
            no_grad = False
        if no_grad:
            with torch.no_grad():
                if autocast: 
                    with torch.cuda.amp.autocast():
                        result = self.local_forward(**kwargs)
                else:
                    result = self.local_forward(**kwargs)
        else:
            if autocast:
                with torch.cuda.amp.autocast():
                    result = self.local_forward(**kwargs)
            else:
                result = self.local_forward(**kwargs)
        # import ipdb; ipdb.set_trace()
        return result

    def local_forward(self, **kwargs):
        raise NotImplementedError
    @property
    def device(self):
        # deepspeed has .module.device to access device
        if not hasattr(self, '_device'):
            self.set_device(device=None)
            
        return self._device

    def set_device(self, device:str = None):
        if device is None:
            device = 'cuda' if torch.cuda.is_available() else 'cpu'
        device = self.resolve_device(device)
        self._device = device
        self.to(device)
        return self._device
    
    
    def forward(self, x: Union[Dict, torch.Tensor])-> Union[torch.Tensor, Dict]:
        raise NotImplementedError
    
    
    def calculate_metrics(self, x: Dict) -> Dict:
        raise NotImplementedError
        
    def set_stat(self, key:str, value:Any) -> Dict[str, Any]: 
        if not hasattr(self, 'stats'):
            self.stats = {'tag': self.tag}
        self.stats[key] = value
        return value
    
    def get_stat(self, key:str,default_value:Any= None) -> Any: 
        if not hasattr(self, 'stats'):
            self.stats = {'tag': self.tag}
        return self.stats.get(key, default_value)
    

    def get_stats(self ) -> dict:
        return self.stats

    @property
    def module_tag(self): 
        return self.resolve_module_tag()
    
    def resolve_module_tag(self, tag=None):
        tag = tag if tag else self.tag
        module_tag = self.model_name.replace("/", "_")
        if tag:
            module_tag +=  f'_{tag}'
        return module_tag
    

    def save(self, tag:str = None, trainable_only:bool = True):
        module_tag = self.resolve_module_tag(tag=tag)
        path = self.resolve_path(module_tag)
        model_state_dict = self.state_dict()
        
        if trainable_only:
            model_state_dict = {k:v for k,v in model_state_dict.items() if v.requires_grad} 
    
        os.makedirs(os.path.dirname(path), exist_ok=True)
        state_dict = {
            'model': model_state_dict,
            'optimizer': self.optimizer.state_dict(),
            'stats': self.stats,
            'metrics': self.metrics.to_dict(),
            'config': self.config
        }
        
        logger.success(f'Saving path {path}')
        
    
        torch.save(state_dict, path)
        
        return path
    
    def load(self, tag=None):
        module_tag = self.resolve_module_tag(tag=tag)
        path = self.resolve_path(module_tag)
        if not os.path.exists(path):
            logger.warning('No saved model found at {path}')
            return
        loaded_state  = torch.load( path)
        state_dict = self.state_dict()
        
        
        for k,v in loaded_state['model'].items():
            assert k in state_dict
            state_dict[k] = v
            
        self.load_state_dict(state_dict)
        self.optimizer.load_state_dict(loaded_state['optimizer'])
        self.metrics = MetricMap.from_dict(loaded_state.get('metrics', {}))
        self.set_stats(**loaded_state['stats'])
        

    def set_fine_tuning_params(self, num_layers:int=1, layer_name:str = None, all:bool = False) -> Tuple[bool, str]:
        r''' Set to tune only the parameter of the last layer
            Returns: 
                reached_last_layer (:type:`bool`):
                    If we have set partial of the model to requires grad.
                
                last_layer_name (:type:`string`):
                    The name of the last layer that user specified or we found.
                    None if the user did not specify and we couldnt find it. 
        '''
        def find_last_layer(model: torch.nn.Module) -> Optional[str]:    
            r''' Recursively find the last layer in a nn.ModuleList
                Args:
                    model (:obj:`torch.module`):
                        The model (or sub-model) to fine the last layer from. 
                Returns:
                    name (:type:`str`):
                        The name (or sub-name) of the last layer.
                        None if not found
            '''
            reverted_child_list = [(name, child) for name, child in model.named_children()]
            reverted_child_list.reverse()

            for name, child in reverted_child_list:    
                if isinstance(child, nn.ModuleList):
                    if num_layers > len(child):
                        logger.warning(f'Number of finetune layers was set higher then the layers avaliable {len(child)}')
                        return None
                    return (name + '.' +str(len(child) - num_layers))
                
            for name, child in reverted_child_list:    
                name_ = find_last_layer(child)
                if name_ != None:
                    return (name+'.'+ name_)

            return None     

        if layer_name == None:
            last_layer_name = find_last_layer(self)
        else:
            last_layer_name = layer_name

        reached_last_layer = False

        # set the non-last layer parameters not to require grads
        if (all) or (last_layer_name == None):
            return False, last_layer_name

        logger.success(f'Set to finetune layer {last_layer_name} and onwards')
        
        for name, param in self.named_parameters():
            if last_layer_name in name or reached_last_layer == True:
                param.requires_grad = True
                reached_last_layer = True
            else:
                param.requires_grad = False

        if reached_last_layer == False:
            if all:
                logger.warning('Set to finetune the whole model, this will significantly increase the memory usage.')
            else:
                logger.warning(f'Cannot identify the last layer of the model with name {last_layer_name}, setting to finetune on all of the parameters.')

        return reached_last_layer, last_layer_name


    @classmethod
    def run_train(cls, 
                    model:str='gpt125m',
                    tag:str = 'demo', 
                    num_batches:int = 10000,
                    window_size:int = 50,
                    backoff_window_size:int = 25,
                    max_iters_since_best:int = 100,
                    dataset:str= 'dataset::bittensor',
                    **kwargs
                    ):
        model = cls(model_name=model,tag=tag, load=True,  **kwargs)
        dataset = commune.connect(dataset)
    
        best_loss = 10e10
        stats = model.get_stats()
        stats['best_loss'] = stats.get('loss', best_loss)
        
        if stats['best_loss'] < 0.1:
            stats['best_loss'] = 10e10
        
        commune.log(f'Loaded {stats} from {tag}', 'yellow')

        
        # if epoch > 0:
        #     model.load(tag=tag)
        fail_count = 0
        iters_since_best = 0
        for i in range(num_batches):
            
            if iters_since_best > max_iters_since_best:
                model.load(tag=tag)
            sample = dataset.sample()
            
            if not (isinstance(sample, dict) and 'input_ids' in sample):
                fail_count += 1
                commune.log(f'Failed to get sample {fail_count} times', 'red')
                continue
            
            
            loss = model.learn_step(**sample)
            
            # update the metric_window
            metric.update(loss)
            window_loss  = metric.value
        
            if verbose:
                info_str = f'Batch {i}/{num_batches} CE: {loss} : {window_loss} Best Loss: {best_loss}'
                commune.log(info_str, 'purple')
                
            if window_loss < best_loss and i > window_size and iters_since_best > backoff_window_size:
                best_loss = window_loss
                model.set_stats(loss=best_loss)
                commune.log(f'Best Stats: {model.get_stats()} ', 'green')
                iters_since_best = 0
                model.save(tag=tag)

                
            else:
                iters_since_best += 1
       
    def set_stats(self, **kwargs):
        if not hasattr(self, 'stats'):
            self.stats = {'tag': self.tag}
        self.stats.update(kwargs)
    @classmethod
    def resolve_device(cls, device:str = None) -> str:
        return commune.resolve_device(device=device)

if __name__ == "__main__":
    
    TransformerModel.run()
    # TransformerModel.test()

