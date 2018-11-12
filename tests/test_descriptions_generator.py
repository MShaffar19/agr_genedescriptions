import logging
import unittest
import os

from genedescriptions.commons import Module
from genedescriptions.config_parser import GenedescConfigParser, ConfigModuleProperty
from genedescriptions.data_manager import DataManager, DataType
from genedescriptions.descriptions_generator import OntologySentenceGenerator

logger = logging.getLogger("Gene Ontology Module tests")


class TestDescriptionsGenerator(unittest.TestCase):

    def setUp(self):
        logger.info("Starting Ontology Tools tests")
        self.this_dir = os.path.split(__file__)[0]
        self.conf_parser = GenedescConfigParser(os.path.join(self.this_dir, os.path.pardir, "tests", "config_test.yml"))
        self.df = DataManager(do_relations=None, go_relations=["subClassOf", "BFO:0000050"])
        logger.info("Loading go ontology from file")
        logging.basicConfig(filename=None, level="ERROR", format='%(asctime)s - %(name)s - %(levelname)s: %(message)s')
        self.df.load_ontology_from_file(ontology_type=DataType.GO, ontology_url="file://" + os.path.join(
            self.this_dir, os.path.pardir, "tests", "data", "go.obo"),
                                        ontology_cache_path=os.path.join(self.this_dir, os.path.pardir, "tests",
                                                                         "cache", "go.obo"), config=self.conf_parser)
        logger.info("Loading go associations from file")
        self.df.load_associations_from_file(associations_type=DataType.GO, associations_url="file://" + os.path.join(
            self.this_dir, os.path.pardir, "tests", "data", "go_annotations.gaf"),
                                            associations_cache_path=os.path.join(self.this_dir, os.path.pardir, "tests",
                                                                                 "cache", "go_annotations.gaf"),
                                            config=self.conf_parser)
        logging.basicConfig(filename=None, level="INFO", format='%(asctime)s - %(name)s - %(levelname)s: %(message)s')

    def test_trimming(self):
        generator = OntologySentenceGenerator(gene_id="WB:WBGene00000912", module=Module.GO,
                                              data_manager=self.df, config=self.conf_parser)
        sentences = generator.get_module_sentences(config=self.conf_parser, aspect='P',
                                                   qualifier='', merge_groups_with_same_prefix=True,
                                                   keep_only_best_group=True, high_priority_term_ids=['GO:0007568',
                                                                                                      'GO:1900426'])
        self.assertTrue("several processes" in sentences.get_description())
        self.assertTrue("aging" in sentences.get_description())
        self.assertTrue("positive regulation of defense response to bacterium" in sentences.get_description())
        self.assertTrue("regulation of cellular biosynthetic process" in sentences.get_description())


