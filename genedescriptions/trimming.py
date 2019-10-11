import logging
from abc import ABCMeta, abstractmethod
from collections import defaultdict
from dataclasses import dataclass
from typing import List, Set, Union, Tuple

from ontobio import Ontology

logger = logging.getLogger(__name__)


@dataclass
class TrimmingCandidate:
    node_id: str
    node_label: str
    covered_starting_nodes: Set[str]


class TrimmingAlgorithm(metaclass=ABCMeta):

    def __init__(self, ontology: Ontology, min_distance_from_root: int = 3, nodeids_blacklist: List[str] = None):
        self.ontology = ontology
        self.min_distance_from_root = min_distance_from_root
        self.nodeids_blacklist = nodeids_blacklist

    @abstractmethod
    def trim(self, node_ids: List[str], max_num_nodes: int = 3):
        pass

    @classmethod
    def __subclasshook__(cls, C):
        if cls is TrimmingAlgorithm:
            if any("trim" in B.__dict__ for B in C.__mro__):
                return True
        return NotImplemented

    def nodes_have_same_root(self, node_ids: List[str]) -> Union[bool, str]:
        """
        Check whether all provided nodes are connected to the same root only

        Args:
            node_ids (List[str]): List of nodes to be checked

        Returns:
            Union[bool, str]: the ID of the common root if all nodes are connected to the same and only root,
                              False otherwise
        """
        common_root = None
        for node_id in node_ids:
            onto_node = self.ontology.node(node_id)
            if "meta" in onto_node and "basicPropertyValues" in onto_node["meta"]:
                for basic_prop_val in onto_node["meta"]["basicPropertyValues"]:
                    if basic_prop_val["pred"] == "OIO:hasOBONamespace":
                        if common_root and common_root != basic_prop_val["val"]:
                            return False
                        common_root = basic_prop_val["val"]
        return common_root

    def get_all_trimming_candidates(self, node_ids: List[str], min_distance_from_root: int = 0):
        """
        Retrieve all common ancestors for the provided list of nodes

        Args:
            node_ids (List[str]): list of starting nodes
            min_distance_from_root (int): minimum distance from root node

        Returns:
            List[TrimmingCandidate]: list of common ancestors
        """
        common_root = self.nodes_have_same_root(node_ids=node_ids)
        if not common_root:
            raise ValueError("Cannot get common ancestors of nodes connected to different roots")
        ancestors = defaultdict(list)
        for node_id in node_ids:
            for ancestor in self.ontology.ancestors(node=node_id, reflexive=True):
                onto_anc = self.ontology.node(ancestor)
                onto_anc_root = None
                if "meta" in onto_anc and "basicPropertyValues" in onto_anc["meta"]:
                    for basic_prop_val in onto_anc["meta"]["basicPropertyValues"]:
                        if basic_prop_val["pred"] == "OIO:hasOBONamespace":
                            onto_anc_root = basic_prop_val["val"]
                if onto_anc["depth"] >= min_distance_from_root and (not onto_anc_root or onto_anc_root ==
                                                                         common_root) and (not self.nodeids_blacklist
                                                                                           or ancestor not in
                                                                                           self.nodeids_blacklist):
                    ancestors[ancestor].append(node_id)
        return [TrimmingCandidate(node_id=ancestor, node_label=self.ontology.label(ancestor),
                                  covered_starting_nodes=set(covered_nodes)) for ancestor, covered_nodes in
                ancestors.items() if len(covered_nodes) > 1 or ancestor == covered_nodes[0]]

    def find_set_covering(self, subsets: List[TrimmingCandidate], value: List[float] = None,
                          max_num_subsets: int = None) -> Union[None, List[Tuple[str, Set[str]]]]:
        """greedy algorithm to solve set covering problem on subsets of trimming candidates

        Args:
            subsets (List[Tuple[str, str, Set[str]]]): list of subsets, each of which must contain a tuple with the first
            element being the ID of the subset, the second being the name, and the third the actual set of elements
            value (List[float]): list of costs of the subsets
            max_num_subsets (int): maximum number of subsets in the final list
        Returns:
            Union[None, List[str]]: the list of IDs of the subsets that maximize coverage with respect to the elements
                                    in the element universe
        """
        logger.debug("starting set covering optimization")
        elem_to_process = {subset.node_id for subset in subsets}
        if value and len(value) != len(elem_to_process):
            return None
        universe = set([e for subset in subsets for e in subset.covered_starting_nodes])
        included_elmts = set()
        included_sets = []
        while len(elem_to_process) > 0 and included_elmts != universe and (not max_num_subsets or len(included_sets) <
                                                                           max_num_subsets):
            if value:
                effect_sets = sorted([(v * len(s.covered_starting_nodes - included_elmts), s.covered_starting_nodes,
                                       s.node_label, s.node_id) for s, v in zip(subsets, value) if s.node_id in
                                      elem_to_process], key=lambda x: (- x[0], x[2]))
            else:
                effect_sets = sorted([(len(s.covered_starting_nodes - included_elmts), s.covered_starting_nodes,
                                       s.node_label, s.node_id) for s in subsets if s.node_id in elem_to_process],
                                     key=lambda x: (- x[0], x[2]))
            elem_to_process.remove(effect_sets[0][3])
            if self.ontology:
                for elem in included_sets:
                    if effect_sets[0][3] in self.ontology.ancestors(elem[0]):
                        included_sets.remove(elem)
            included_elmts |= effect_sets[0][1]
            included_sets.append((effect_sets[0][3], effect_sets[0][1]))
        logger.debug("finished set covering optimization")
        return included_sets


class TrimmingAlgorithmIC(TrimmingAlgorithm):

    def __init__(self, ontology: Ontology, min_distance_from_root: int = 3, nodeids_blacklist: List[str] = None,
                 slim_terms_ic_bonus_perc: int = 0, slim_set: set = None):
        super().__init__(ontology, min_distance_from_root, nodeids_blacklist)
        self.slim_terms_ic_bonus_perc = slim_terms_ic_bonus_perc
        self.slim_set = slim_set

    def get_candidate_ic_value(self, candidate: TrimmingCandidate, node_ids: List[str],
                               slim_terms_ic_bonus_perc: int = 0, slim_set: set = None):
        """
        Calculate the information content value of a candidate node

        Args:
            candidate (TrimmingCandidate): the candidate node
            node_ids (List[str]): the original set of nodes to be trimmed
            slim_terms_ic_bonus_perc (int): boost the IC value for terms that appear in the slim set by the provided
                                            percentage
            slim_set (set): set of terms that belong to the slim for the provided ontology

        Returns:
            float: the information content value of the candidate node
        """
        candidate_node = self.ontology.node(candidate.node_id)
        if candidate.node_id not in node_ids and candidate_node["depth"] < self.min_distance_from_root:
            return 0
        elif slim_set and candidate.node_id in slim_set:
            return candidate_node["IC"] * (1 + slim_terms_ic_bonus_perc)
        else:
            return candidate_node["IC"]

    def trim(self, node_ids: List[str], max_num_nodes: int = 3):
        """trim the list of terms by selecting the best combination of terms from the initial list or their common
        ancestors based on information content

        Args:
            node_ids (List[str]): the list of nodes to merge by common ancestor
            max_num_nodes (int): maximum number of nodes to be included in the trimmed set. This also represents the
                                 minimum number of terms above which the merge operation is performed
        Returns:
            Set[str]: the set of trimmed terms, together with the set of original terms that each of them covers
        """
        common_ancestors = self.get_all_trimming_candidates(node_ids=node_ids)
        values = [self.get_candidate_ic_value(candidate=candidate, node_ids=node_ids,
                                              slim_terms_ic_bonus_perc=self.slim_terms_ic_bonus_perc,
                                              slim_set=self.slim_set) for candidate in common_ancestors]
        if self.slim_set and any([node.node_id in self.slim_set for node in common_ancestors]):
            logger.debug("some candidates are present in the slim set")
        # remove ancestors with zero IC
        common_ancestors = [common_ancestor for common_ancestor, value in zip(common_ancestors, values) if value > 0]
        values = [value for value in values if value > 0]
        best_terms = self.find_set_covering(subsets=common_ancestors, max_num_subsets=max_num_nodes, value=values)
        covered_terms = set([e for best_term_label, covered_terms in best_terms for e in covered_terms])
        return covered_terms != set(node_ids), best_terms


class TrimmingAlgorithmLCA(TrimmingAlgorithm):

    def __init__(self, ontology: Ontology, min_distance_from_root: int = 3, nodeids_blacklist: List[str] = None):
        super().__init__(ontology, min_distance_from_root, nodeids_blacklist)

    def trim(self, node_ids: List[str], max_num_nodes: int = 3):
        candidates_dict = {candidate.node_id: (candidate.node_label, candidate.covered_starting_nodes) for candidate in
                           self.get_all_trimming_candidates(node_ids=node_ids,
                                                            min_distance_from_root=self.min_distance_from_root)}
        cands_ids_to_process = set(candidates_dict.keys())
        selected_cands_ids = []
        node_to_cands_map = defaultdict(list)
        for cand in cands_ids_to_process:
            for node in candidates_dict[cand][1]:
                node_to_cands_map[node].append(cand)
        while len(cands_ids_to_process) > 0:
            cand_id = cands_ids_to_process.pop()
            comparable_cands = [(cid, cval[1]) for cid, cval in candidates_dict.items() if cid != cand_id and all(
                [child_id in cval[1] for child_id in candidates_dict[cand_id][1]])]
            if len(comparable_cands) > 0:
                max_len = max(map(lambda x: len(x[1]), comparable_cands))
                best_cands = [candidate for candidate in comparable_cands if len(candidate[1]) == max_len]
                if len(best_cands) > 1:
                    weighted_best_cands = sorted([(self.ontology.node(cand[0])["depth"], cand) for cand in best_cands],
                                                 key=lambda x: x[0], reverse=True)
                    max_weight = max(map(lambda x: x[0], weighted_best_cands))
                    best_cands = [wcand[1] for wcand in weighted_best_cands if wcand[0] == max_weight]
                else:
                    max_weight = self.ontology.node(best_cands[0][0])["depth"]
                if len(candidates_dict[cand_id][1]) > len(best_cands[0][1]) or \
                    (len(candidates_dict[cand_id][1]) > len(best_cands[0][1]) and
                     self.ontology.node(cand_id)["depth"] > max_weight):
                    best_cands = [(cand_id, candidates_dict[cand_id][1])]
                for best_cand in best_cands:
                    selected_cands_ids.append(best_cand[0])
                    for node_id in candidates_dict[best_cand[0]][1]:
                        cands_ids_to_process -= set(node_to_cands_map[node_id])
            else:
                selected_cands_ids.append(cand_id)
        if len(selected_cands_ids) <= max_num_nodes:
            return False, [(node_id, candidates_dict[node_id][1]) for node_id in selected_cands_ids]

        else:
            best_terms = self.find_set_covering(
                [TrimmingCandidate(node_id, self.ontology.label(node_id, id_if_null=True), candidates_dict[node_id][1])
                 for node_id in selected_cands_ids], max_num_subsets=max_num_nodes)
            covered_terms = set([e for best_term_label, covered_terms in best_terms for e in covered_terms])
            return covered_terms != set(node_ids), best_terms


class TrimmingAlgorithmNaive(TrimmingAlgorithm):

    def __init__(self, ontology: Ontology, min_distance_from_root: int = 3, nodeids_blacklist: List[str] = None):
        super().__init__(ontology, min_distance_from_root, nodeids_blacklist)

    def trim(self, node_ids: List[str], max_num_nodes: int = 3):
        logger.debug("applying trimming through naive algorithm")
        final_terms_set = {}
        ancestor_paths = defaultdict(list)
        term_paths = defaultdict(set)
        # step 1: get all path for each term and populate data structures
        for node_id in node_ids:
            node_root = None
            node_ont = self.ontology.node(node_id)
            if "meta" in node_ont and "basicPropertyValues" in node_ont["meta"]:
                for basic_prop_val in node_ont["meta"]["basicPropertyValues"]:
                    if basic_prop_val["pred"] == "OIO:hasOBONamespace":
                        node_root = basic_prop_val["val"]
            paths = self.get_all_paths_to_root(node_id=node_id, ontology=self.ontology,
                                               min_distance_from_root=self.min_distance_from_root, relations=None,
                                               nodeids_blacklist=self.nodeids_blacklist, root_node=node_root)
            for path in paths:
                term_paths[node_id].add(path)
                ancestor_paths[path[-1]].append(path)
        # step 2: merge terms and keep common ancestors
        for node_id in sorted(node_ids):
            term_paths_copy = sorted(term_paths[node_id].copy(), key=lambda x: len(x))
            while len(term_paths_copy) > 0:
                curr_path = list(term_paths_copy.pop())
                selected_highest_ancestor = curr_path.pop()
                related_paths = ancestor_paths[selected_highest_ancestor]
                if not related_paths:
                    break
                covered_nodes_set = set([related_path[0] for related_path in related_paths])
                del ancestor_paths[selected_highest_ancestor]
                if curr_path:
                    if all(map(lambda x: x[0] == curr_path[0], related_paths)):
                        selected_highest_ancestor = curr_path[0]
                    else:
                        i = -1
                        while len(curr_path) > 1:
                            i -= 1
                            curr_highest_ancestor = curr_path.pop()
                            if not all(map(lambda x: len(x) >= - i, related_paths)):
                                break
                            if all(map(lambda x: x[i] == curr_highest_ancestor, related_paths)):
                                selected_highest_ancestor = curr_highest_ancestor
                                if selected_highest_ancestor in ancestor_paths:
                                    del ancestor_paths[selected_highest_ancestor]
                                for path in related_paths:
                                    term_paths[path[0]].discard(path)
                final_terms_set[selected_highest_ancestor] = covered_nodes_set
                for path in related_paths:
                    term_paths[path[0]].discard(path)
                if len(term_paths[node_id]) > 0:
                    term_paths_copy = term_paths[node_id].copy()
                else:
                    break
        if len(list(final_terms_set.keys())) <= max_num_nodes:
            return False, [(term_label, covered_terms) for term_label, covered_terms in final_terms_set.items()]

        else:
            best_terms = self.find_set_covering(
                [TrimmingCandidate(k, self.ontology.label(k, id_if_null=True), v) for k, v in final_terms_set.items()],
                max_num_subsets=max_num_nodes)
            covered_terms = set([e for best_term_label, covered_terms in best_terms for e in covered_terms])
            return covered_terms != set(node_ids), best_terms

    @staticmethod
    def get_all_paths_to_root(node_id: str, ontology: Ontology, min_distance_from_root: int = 0,
                              relations: List[str] = None, nodeids_blacklist: List[str] = None,
                              previous_path: Union[None, List[str]] = None, root_node=None) -> Set[Tuple[str]]:
        """get all possible paths connecting a go term to its root terms

        Args:
            node_id (str): a valid GO id for the starting term
            ontology (Ontology): the go ontology
            min_distance_from_root (int): return only terms at a specified minimum distance from root terms
            relations (List[str]): the list of relations to be used
            nodeids_blacklist (List[str]): a list of node ids to exclude from the paths
            previous_path (Union[None, List[str]]): the path to get to the current node
        Returns:
            Set[Tuple[str]]: the set of paths connecting the specified term to its root terms, each of which contains a
            sequence of terms ids
        """
        if previous_path is None:
            previous_path = []
        new_path = previous_path[:]
        if not nodeids_blacklist or node_id not in nodeids_blacklist:
            new_path.append(node_id)
        parents = [parent for parent in ontology.parents(node=node_id, relations=relations) if
                   ontology.node(parent)["depth"] >= min_distance_from_root]
        parents_same_root = []
        if root_node:
            for parent in parents:
                parent_node = ontology.node(parent)
                parent_root = None
                if "meta" in parent_node and "basicPropertyValues" in parent_node["meta"]:
                    for basic_prop_val in parent_node["meta"]["basicPropertyValues"]:
                        if basic_prop_val["pred"] == "OIO:hasOBONamespace":
                            parent_root = basic_prop_val["val"]
                if parent_root and parent_root == root_node:
                    parents_same_root.append(parent)
            parents = parents_same_root

        if len(parents) > 0:
            # go up the tree, following a depth first visit
            paths_to_return = set()
            for parent in parents:
                for path in TrimmingAlgorithmNaive.get_all_paths_to_root(node_id=parent, ontology=ontology,
                                                                         previous_path=new_path,
                                                                         min_distance_from_root=min_distance_from_root,
                                                                         relations=relations,
                                                                         nodeids_blacklist=nodeids_blacklist,
                                                                         root_node=root_node):
                    paths_to_return.add(path)
            return paths_to_return
        if len(new_path) == 0:
            return {(node_id,)}
        else:
            return {tuple(new_path)}
