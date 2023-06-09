import math
import ml
from ml.Variable import Variable
from modules.layers import Layer , Linear , Dropout , LayerNorm , Lambda , Embedding
from modules.containers import Sequential

class CausalSelfAttention(Layer):

    def __init__(self ,
                  n_embed ,
                  n_head  , 
                  block_size,
                  attn_dropout_rate,
                  resid_dropout_rate
                  ):
        super(CausalSelfAttention,self).__init__()

        self.c_attn = Linear(3 * n_embed , weight_initializer= ml.initializers.RandomNormal(mean=0,std=.02))
        self.c_proj = Linear(n_embed)
        self.attn_dropout = Dropout(attn_dropout_rate)
        self.resid_dropout = Dropout(resid_dropout_rate)
        self.bias = ml.ones((1,1,block_size,block_size), requires_grad = False, dtype='bool').tril()
        self.n_head = n_head
        self.n_embd = n_embed
        
    def call(self , x):
        B , T , C = x.shape
        q , k , v = self.c_attn(x).split( 3 , axis=2)

        k :ml.tensor = k.reshape(B , T , self.n_head , C // self.n_head).transpose(1,2)
        q :ml.tensor = q.reshape(B , T , self.n_head , C // self.n_head).transpose(1,2)
        v :ml.tensor = v.reshape(B , T , self.n_head , C // self.n_head).transpose(1,2)

        #(B, nh, T, hs) x (B, nh, hs, T) -> (B, nh, T, T)
        att = ml.linalg.matmul(k , q, transpose_b=True) * (1.0 / math.sqrt(k.shape[-1]))
   
        att = ml.ops.where(self.bias[:,:,:T,:T] == 0  , float('-inf') , att )
        att = ml.activations.softmax(att , dim= -1)
        att = self.attn_dropout(att)

        y = att @ v 
        y = y.transpose(1,2).contiguous().reshape(B,T,C)
        y = self.resid_dropout(self.c_proj(y))
        return y
    

class Block(Layer):

    def __init__(self,
                 n_embed ,
                 n_head  , 
                 block_size,
                 attn_dropout_rate,
                 resid_dropout_rate
                 ):
        super(Block , self).__init__()

        self.ln_1 = LayerNorm()
        self.attn = CausalSelfAttention(n_embed ,n_head  , block_size,attn_dropout_rate, resid_dropout_rate)
        self.ln_2 = LayerNorm()
        self.mlp = Sequential([
            Linear(4 * n_embed),
            Lambda( lambda x : ml.activations.gelu(x , use_approx= False) ),
            Linear(n_embed),
            Dropout(resid_dropout_rate)
        ])

    def call(self , x):
        x  = self.attn(self.ln_1(x)) + x #residual conn
        x  = self.mlp(self.ln_2(x)) + x #residual conn
        return x
    

class Transformer(Layer):
    def __init__(self ,
                  n_layers,
                  vocab_size , 
                  block_size ,
                  n_embd , 
                  n_head,
                  dropout_rate,
                  attn_dropout_rate,
                  resid_dropout_rate
                  ):
        super(Transformer , self).__init__()
        self.wte = Embedding(vocab_size , n_embd)
        self.wpe = Embedding(block_size , n_embd)
        self.drop = Dropout(dropout_rate)
        self.h = Sequential([
            Block(n_embd,n_head,block_size,attn_dropout_rate , resid_dropout_rate) 
            for _ in range(n_layers)
            ])
        self.lm_head = Linear(vocab_size , use_bias= False)
        
    def call(self , IDX :ml.tensor ):
        B , T = IDX.shape

        pos :ml.tensor = ml.arange(0 , T , dtype='int64',requires_grad=False).unsqueeze(0)

        tok_embd = self.wte(IDX)
        pos_emb = self.wpe(pos)

        x = self.drop(tok_embd + pos_emb)
        x = self.h(x)

        return self.lm_head(x)
    

 ####################### im still playing with these not sure if they work #############################################################################################   

def rotate_half(x : Variable ) ->Variable :
    x  = x.reshape(*x.shape[:-1],x.shape[-1]//2 , 2 )
    x1, x2 = x.unstack(axis = -2)
    return ml.ops.concat((-x2 , x1), axis = -1)


def apply_rotary_pos_emb(pos : Variable , t : Variable) ->Variable:
    return ( t * pos.cos() ) + ( rotate_half(t) * pos.sin() )

class RotaryEmbedding(Layer):

    def __init__(self, dim):
        super().__init__()
        self.invFreq = 1. / (10000 ** (ml.arange(0, dim ,2 , dtype = 'float32' ,requires_grad= False)) / dim )
             
    def call(self, max_seq_len) ->Variable :
        seq : Variable = ml.arange(0 , max_seq_len , dtype = self.invFreq.dtype)
        freqs = seq.outer_product(self.invFreq)
        return ml.ops.concat((freqs,freqs) , axis = -1)
 

