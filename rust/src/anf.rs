extern crate generational_arena;

use self::generational_arena::{Arena, Index};
use std::collections::{HashSet, HashMap};
use std::any::{Any, TypeId};
use std::ptr;

struct Graph<'a> {
    parameters: Vec<ANFNodePtr<'a>>,
    return_: Option<ANFNodePtr<'a>>,
    //debug:
    //transforms: HashMap<String, GraphPtr>,
}

#[derive(Copy, Clone)]
pub struct GraphPtr<'a> {
    p: Index,
    manager: &'a GraphManager<'a>
}

impl<'a> GraphPtr<'a> {
    fn get(&self) -> &Graph {
        &self.manager.graphs[self.p]
    }

    pub fn get_output(&'a self) -> Option<ANFNodePtr<'a>> {
        let ret = self.get().return_;
        ret
    }
}

enum ANFNodeType<'a> {
    Apply(Vec<ANFNodePtr<'a>>),
    Parameter,
    Constant(Box<dyn Any>),
}

struct ANFNode<'a> {
    node: ANFNodeType<'a>,
    graph: Option<GraphPtr<'a>>
}

pub struct ANFNodeInputIter<'a> {
    vals: &'a ANFNodeType<'a>,
    p: usize
}

impl<'a> ANFNodeInputIter<'a> {
    fn new(node: &'a ANFNode<'a>) -> Self {
        ANFNodeInputIter { vals: &node.node, p: 0 }
    }
}

impl<'a> Iterator for ANFNodeInputIter<'a> {
    type Item = ANFNodePtr<'a>;

    fn next(&mut self) -> Option<Self::Item> {
        if let ANFNodeType::Apply(inps) = self.vals {
            let elem = inps.get(self.p);
            self.p += 1;
            if let Some(v) = elem {
                Some(*v)
            } else {
                None
            }
        } else {
            None
        }
    }
}

#[derive(Copy, Clone)]
pub struct ANFNodePtr<'a> {
    p: Index,
    manager: &'a GraphManager<'a>
}

impl<'a> ANFNodePtr<'a> {
    fn get(&self) -> &ANFNode {
        &self.manager.all_nodes[self.p]
    }

    pub fn incoming(&'a self) -> ANFNodeInputIter<'a> {
        ANFNodeInputIter::new(self.get())
    }

    pub fn value(&'a self) -> Option<&'a Box<dyn Any>> {
        if let ANFNodeType::Constant(v) = &self.get().node {
            Some(v)
        } else {
            None
        }
    }

    pub fn is_apply(&self, value: Option<&dyn Any>) -> bool {
        if let Some(v) = value {
            if let ANFNodeType::Apply(inps) = &self.get().node {
                // If a node has a value, it's a constant
                if let Some(func) = inps[0].value() {
                    ptr::eq(func.as_ref(), v)
                } else {
                    false
                }
            } else {
                false
            }
        } else {
            matches!(&self.get().node, ANFNodeType::Apply(_))
        }
    }

    pub fn is_parameter(&self) -> bool {
        matches!(&self.get().node, ANFNodeType::Parameter)
    }

    pub fn is_constant(&self, value: Option<TypeId>) -> bool {
        if let Some(vv) = value {
            if let ANFNodeType::Constant(v) = &self.get().node {
                v.type_id() == vv
            } else {
                false
            }
        } else {
            matches!(&self.get().node, ANFNodeType::Constant(_))
        }
    }
}

pub struct GraphManager<'a> {
    roots: HashSet<ANFNodePtr<'a>>,
    all_nodes: Arena<ANFNode<'a>>,
    graphs: Arena<Graph<'a>>,
}

impl<'a> GraphManager<'a> {
    pub fn new() -> Self {
        GraphManager { roots: HashSet::<ANFNodePtr<'a>>::new(),
                       all_nodes: Arena::new(),
                       graphs: Arena::new() }
    }

    pub fn new_graph(&mut self) -> GraphPtr {
        let p = Vec::new();
        let g = self.graphs.insert(Graph { parameters: p, return_: None });
        let s = &*self;
        GraphPtr { p: g, manager: s }
    }

    pub fn alloc_apply(&mut self, params: Vec<ANFNodePtr<'a>>) -> ANFNodePtr {
        let n = ANFNodeType::Apply(params);
        let a = self.all_nodes.insert(ANFNode { node: n, graph: None });
        let s = &*self;
        ANFNodePtr { p: a, manager: s }
    }
}
