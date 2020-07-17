from stacker.blueprints.base import Blueprint
from stacker.blueprints.variables.types import TroposphereType
from troposphere import Output, Ref, Tags
from troposphere import msk


class _Cluster(msk.Cluster):
    """Class to replace Tags property, since original troposphere type does not
    accept a list of tags
    """
    props = msk.Cluster.props
    props.update({
        'Tags': ((Tags, list), False)
    })


class Cluster(Blueprint):
    VARIABLES = {
        'Clusters': {
            'type': TroposphereType(_Cluster, many=True),
            'description': 'A dictinary where key is the resource name and '
                           'the value is a MSK cluster as defined by '
                           'Cloudformation'
        }
    }

    def create_template(self):
        v = self.get_variables()
        t = self.template

        clusters = v.get('Clusters')
        for cluster in clusters:
            t.add_resource(cluster)
            t.add_output(Output(cluster.title, Value=Ref(cluster)))
