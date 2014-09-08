import random
import string

from fabric.api import env, execute, put
from fabric.context_managers import cd
from fabric.contrib.files import upload_template
from fabric.decorators import roles, runs_once
from ec2 import *

env.ec2_key_pair_name = 'exabytes18@geneva'
env.ec2_vpc_id = 'vpc-eed33c8b'
env.ec2_region = 'us-west-1'
env.ec2_instances = {
    'data-nodes': {
        'roles': ['data-node'],
        'type': 'r3.2xlarge',
        'ami': 'ami-f0d3d4b5',
        'count': 2,
        'bid': 0.50,
        'ephemeral_disks': ['/dev/sdb'],
        'assign_public_ip': False,
        'source_dest_check': True,
        'security_groups': ['mysql-cluster'],
        'placement_group': 'mysql-cluster',
        'subnet': 'subnet-cfd3ec89', # Private subnet (i.e., subnet with routing table containing default route to VPN instance)
    },

    'load-generators': {
        'roles': ['load-generator'],
        'type': 'r3.2xlarge',
        'ami': 'ami-f0d3d4b5',
        'count': 1,
        'bid': 0.50,
        'ephemeral_disks': None,
        'assign_public_ip': False,
        'source_dest_check': True,
        'security_groups': ['mysql-cluster'],
        'placement_group': 'mysql-cluster',
        'subnet': 'subnet-cfd3ec89', # Private subnet
    },

    'utility-boxes': {
        'roles': ['mgmt', 'mysqld'],
        'type': 'm3.medium',
        'ami': 'ami-f0d3d4b5',
        'count': 1,
        'bid': 0.02,
        'ephemeral_disks': ['/dev/sdb'],
        'assign_public_ip': False,
        'source_dest_check': True,
        'security_groups': ['mysql-cluster'],
        'placement_group': None,
        'subnet': 'subnet-cfd3ec89', # Private subnet
    },

    'vpn': {
        'roles': ['vpn', 'yum-repo'],
        'type': 'm3.medium',
        'ami': 'ami-f0d3d4b5',
        'count': 1,
        'bid': 0.02,
        'ephemeral_disks': None,
        'assign_public_ip': True,
        'source_dest_check': False,
        'security_groups': ['vpn'],
        'placement_group': None,
        'subnet': 'subnet-895c63cf', # Public Subnet (i.e., subnet with routing table containing default route to internet gateway)
    },
}

env.user = 'ec2-user'
env.roledefs = {
    'vpn-servers': get_instances_callable(
        role='vpn',
        mapper=lambda i: i.ip_address,
        abort_if_none=True),
    'data-nodes': get_instances_callable(
        role='data-node',
        mapper=lambda i: i.private_ip_address,
        abort_if_none=True),
    'load-generators': get_instances_callable(
        role='load-generator',
        mapper=lambda i: i.private_ip_address,
        abort_if_none=True),
    'mgmt-servers': get_instances_callable(
        role='mgmt',
        mapper=lambda i: i.private_ip_address,
        abort_if_none=True),
    'mysqld-servers': get_instances_callable(
        role='mysqld',
        mapper=lambda i: i.private_ip_address,
        abort_if_none=True),
    'yum-repo-servers': get_instances_callable(
        role='yum-repo',
        mapper=lambda i: i.private_ip_address,
        abort_if_none=True),
}


def ip_cmp(a, b):
    for octet_pair in zip(a.split('.'), b.split('.')):
        c = cmp(int(octet_pair[0]), int(octet_pair[1]))
        if c != 0:
            return c
    return 0


@task
@roles('vpn-servers')
def configure_vpn_server():
    instance = get_instance_by_ip(env.host)
    if instance is None:
        abort('\n'
              '\n'
              '    Unable to find the vpn instance!')

    sr = random.SystemRandom()
    random_psk = ''.join(sr.choice(string.hexdigits) for x in xrange(32))

    sudo('yum -y update')
    sudo('yum -y install gcc gmp gmp-devel')
    sudo('mkdir -p /usr/share/strongswan')
    with cd('/usr/share/strongswan'):
        sudo('curl http://download.strongswan.org/strongswan-5.2.0.tar.gz > strongswan-5.2.0.tar.gz')
        sudo('tar -xf strongswan-5.2.0.tar.gz')
        sudo('chown root:root -R strongswan-5.2.0')
        sudo('chmod 755 strongswan-5.2.0')
        with cd('strongswan-5.2.0'):
            sudo('./configure --prefix=/usr --sysconfdir=/etc')
            sudo('make')
            sudo('make install')

    upload_template(
        filename='files/etc/ipsec.conf',
        destination='/etc/ipsec.conf',
        context={
            'gateway_private_ip': instance.private_ip_address
        },
        use_jinja=True,
        use_sudo=True,
        backup=False,
        mode=0644)
    upload_template(
        filename='files/etc/ipsec.secrets',
        destination='/etc/ipsec.secrets',
        context={
            'random_psk': random_psk
        },
        use_jinja=True,
        use_sudo=True,
        backup=False,
        mode=0600)
    sudo('chown root:root /etc/ipsec.conf')
    sudo('chown root:root /etc/ipsec.secrets')

    sudo('sed -i \'s/^net.ipv4.ip_forward.*/net.ipv4.ip_forward = 1/\' /etc/sysctl.conf')
    sudo('sysctl -e -p')

    # Add NAT rule, if it does not already exist
    sudo('iptables --table nat -C POSTROUTING -s 10.0.0.0/16 -j MASQUERADE || '
         'iptables --table nat -A POSTROUTING -s 10.0.0.0/16 -j MASQUERADE')
    sudo('service iptables save')

    sudo('ipsec start')
    print ('\n'
           '    Random preshared key: "%s"\n'
           '\n'
           '\n'
           '    Configure your VPC routing as follows:\n'
           '        Public subnet:\n'
           '            (probably default table created by aws, likely no change needed):\n'
           '                10.0.0.0/16 -> local\n'
           '                0.0.0.0/0   -> Internet Gateway\n'
           '            Use this subnet for the VPN instance (and assign it a public IP).\n'
           '            The VPN instance will also act as a NAT device so instances in\n'
           '            the private subnet will be able to communicate with outside world\n'
           '            (e.g. `ping 8.8.8.8`). Specifically, this subnet should contain\n'
           '            only instances that require public IPs; this includes VPN servers,\n'
           '            public NAT devices, load balancers, etc.\n'
           '\n'
           '        Private subnet:\n'
           '            (custom routing table):\n'
           '                10.0.0.0/16 -> local\n'
           '                0.0.0.0/0   -> "%s" (VPN/NAT instance)\n'
           '            Local traffic within this subnet and to the public subnet should be\n'
           '            fast; however, traffic to outside world will be sluggish as it\n'
           '            will need to traverse the NAT device in the public subnet. Keep\n'
           '            this in mind when determining in which subnet to place instances.\n'
           '            Use this subnet for the MySQL Cluster nodes.\n'
           '\n'
           '\n'
           '    To install strongswan on OSX:\n'
           '        brew install strongswan\n'
           '\n'
           '\n'
           '    To configure strongswan on OSX:\n'
           '        Edit /usr/local/etc/ipsec.conf:\n'
           '            config setup\n'
           '                # nat_traversal=yes\n'
           '            conn %%default\n'
           '                ikelifetime=60m\n'
           '                keylife=20m\n'
           '                rekeymargin=3m\n'
           '                keyingtries=1\n'
           '                keyexchange=ikev2\n'
           '                authby=secret\n'
           '            conn vpc-gw\n'
           '                left=%%any\n'
           '                leftsourceip=%%config\n'
           '                leftid=me@example.com\n'
           '                leftfirewall=yes\n'
           '                right=%s\n'
           '                rightsubnet=10.0.0.0/16\n'
           '                rightid=@vpc-gw\n'
           '                auto=start\n'
           '\n'
           '        Edit /usr/local/etc/ipsec.secrets:\n'
           '            vpc-gw : PSK "%s"\n'
           '\n'
           '        Start VPN connection and test that it works:\n'
           '            sudo ipsec restart\n'
           '            sudo ipsec statusall\n'
           '\n' % (random_psk, instance.id, instance.ip_address, random_psk))


@task
@roles('yum-repo-servers')
def configure_yum_repo():
    sudo('yum -y update')
    sudo('yum -y install nginx createrepo')
    sudo('mkdir -p /www/repos/rpm')
    with cd('/www/repos/rpm'):
        sudo('curl --location http://dev.mysql.com/get/Downloads/MySQL-Cluster-7.3/MySQL-Cluster-server-gpl-7.3.6-2.el6.x86_64.rpm > MySQL-Cluster-server-gpl-7.3.6-2.el6.x86_64.rpm')
        sudo('curl --location http://dev.mysql.com/get/Downloads/MySQL-Cluster-7.3/MySQL-Cluster-client-gpl-7.3.6-2.el6.x86_64.rpm > MySQL-Cluster-client-gpl-7.3.6-2.el6.x86_64.rpm')
        sudo('curl --location http://dev.mysql.com/get/Downloads/MySQL-Cluster-7.3/MySQL-Cluster-devel-gpl-7.3.6-2.el6.x86_64.rpm > MySQL-Cluster-devel-gpl-7.3.6-2.el6.x86_64.rpm')
        sudo('curl --location http://dev.mysql.com/get/Downloads/MySQL-Cluster-7.3/MySQL-Cluster-shared-gpl-7.3.6-2.el6.x86_64.rpm > MySQL-Cluster-shared-gpl-7.3.6-2.el6.x86_64.rpm')
        sudo('curl --location http://dl.fedoraproject.org/pub/epel/6/x86_64/iperf-2.0.5-11.el6.x86_64.rpm > iperf-2.0.5-11.el6.x86_64.rpm')
        sudo('createrepo .')
    upload_template(
        filename='files/etc/nginx/nginx.conf',
        destination='/etc/nginx/nginx.conf',
        use_sudo=True,
        backup=False,
        mode=0644)
    sudo('service nginx start')
    sudo('service nginx reload')


def install_yum_repo_file():
    repo_ip = get_instances_callable(
        role='yum-repo',
        mapper=lambda i: i.private_ip_address)()[0]

    upload_template(
        filename='files/etc/yum.repos.d/mysql-cluster.repo',
        destination='/etc/yum.repos.d/mysql-cluster.repo',
        context={
            'baseurl': 'http://%s/repos/rpm' % repo_ip
        },
        use_jinja=True,
        use_sudo=True,
        backup=False,
        mode=0644)


@roles('data-nodes', 'mgmt-servers', 'mysqld-servers')
def install_servers():
    execute(install_yum_repo_file)
    sudo('yum -y update')
    sudo('yum -y install perl-Data-Dumper')
    sudo('yum -y install MySQL-Cluster-server-gpl')


@roles('mysqld-servers')
def install_mysql_cluster_clients():
    execute(install_yum_repo_file)
    sudo('yum -y update')
    sudo('yum -y install MySQL-Cluster-client-gpl')


@task
def install_mysql_cluster():
    execute(install_servers)
    execute(install_mysql_cluster_clients)


@task
@roles('load-generators')
def install_load_generators():
    execute(install_yum_repo_file)
    sudo('yum -y update')
    sudo('yum -y install gcc-c++ MySQL-Cluster-devel-gpl MySQL-Cluster-shared-gpl MySQL-Cluster-server-gpl')
    put('benchmarks', '.')
    with cd('~/benchmarks/src'):
        run('make')


@roles('mgmt-servers')
def configure_mgmt_nodes():
    sudo('mkdir -p /media/ephemeral0/ndb-data')
    sudo('chown mysql:mysql /media/ephemeral0/ndb-data')
    sudo('mkdir -p /etc/ndb')

    node_id = 0
    
    mgmt_nodes = []
    for node in sorted(get_instances_callable(
            role='mgmt',
            mapper=lambda i: i.private_ip_address)(), ip_cmp):
        node_id += 1
        mgmt_nodes.append((node_id, node))

    data_nodes = []
    for node in sorted(get_instances_callable(
            role='data-node',
            mapper=lambda i: i.private_ip_address)(), ip_cmp):
        node_id += 1
        data_nodes.append((node_id, node))

    # Leave 48 slots for the data nodes between the management nodes and the
    # mysqld nodes. This isn't necessary for such temporary clusters.. but
    # whatever.
    node_id = len(mgmt_nodes) + 48
    mysqld_nodes = []
    for node in sorted(get_instances_callable(
            role='mysqld',
            mapper=lambda i: i.private_ip_address)(), ip_cmp):
        node_id += 1
        mysqld_nodes.append((node_id, node))

    api_nodes = []
    for x in xrange(0, 16):
        node_id += 1
        api_nodes.append((node_id, None))

    upload_template(
        filename='files/etc/ndb/config.ini',
        destination='/etc/ndb/config.ini',
        context={
            'mgmt_nodes': mgmt_nodes,
            'data_nodes': data_nodes,
            'mysqld_nodes': mysqld_nodes,
            'api_nodes': api_nodes,
        },
        use_jinja=True,
        use_sudo=True,
        backup=False,
        mode=0644)


@roles('data-nodes')
def configure_data_nodes():
    sudo('mkdir -p /media/ephemeral0/ndb-data')
    sudo('chown mysql:mysql /media/ephemeral0/ndb-data')


@roles('mysqld-servers')
def configure_mysqld():
    sudo('mkdir -p /media/ephemeral0/mysql-data')
    sudo('chown mysql:mysql /media/ephemeral0/mysql-data')
    upload_template(
        filename='files/usr/my.cnf',
        destination='/usr/my.cnf',
        context={
            'mgmt_nodes': get_instances_callable(
                role='mgmt',
                mapper=lambda i: i.private_ip_address)()
        },
        use_jinja=True,
        use_sudo=True,
        backup=False,
        mode=0644)
    sudo('test -e /media/ephemeral0/mysql-data/ibdata1 || '
         'su - mysql -c mysql_install_db')


@task
def configure_mysql_cluster():
    execute(configure_mgmt_nodes)
    execute(configure_data_nodes)
    execute(configure_mysqld)


@task
@roles('mgmt-servers')
def start_mgmt_nodes():
    # If we break the ssh session before ndb_mgmd has spawned the daemon, we
    # lose it all. Hence, we'll sleep for a few seconds to allow time for the
    # daemon process to start.
    sudo('ndb_mgmd -f /etc/ndb/config.ini --configdir=/etc/ndb --initial && sleep 3')


@roles('data-nodes')
def start_data_nodes():
    mgmt_nodes = get_instances_callable(
        role='mgmt',
        mapper=lambda i: i.private_ip_address)()
    sudo('ndbmtd -c %s' % ','.join(mgmt_nodes))


@roles('mysqld-servers')
def start_mysqld_servers():
    sudo('service mysql start')


@task
def start_mysql_cluster():
    execute(start_mgmt_nodes)
    execute(start_data_nodes)
    execute(start_mysqld_servers)


@runs_once
@roles('mgmt-servers')
def stop_ndb_nodes():
    # We only need one management server to shutdown the entire cluster, hence
    # the @runs_once decorator.
    sudo('ndb_mgm -t 1 -e shutdown || true')


@roles('mysqld-servers')
def stop_mysqld_servers():
    # Beware: mysqld doesn't like to shutdown if it's not connected to the ndb
    # cluster.
    sudo('service mysql stop')


@task
def stop_mysql_cluster():
    execute(stop_mysqld_servers)
    execute(stop_ndb_nodes)


@roles('data-nodes', 'mgmt-servers', 'mysqld-servers')
def nuke_mysql_cluster():
    sudo('rm -rf /media/ephemeral0/ndb-data/*')
    sudo('rm -rf /media/ephemeral0/mysql-data/*')


@runs_once
@roles('mysqld-servers')
def create_schema():
    run('''cat <<EOF | mysql -u root
        CREATE DATABASE benchmarks;
        USE benchmarks;
        CREATE TABLE transactions (
            account_id INT,
            txn_id INT,
            timestamp INT,
            posted BOOLEAN,
            amount FLOAT,
            PRIMARY KEY (account_id, txn_id)
        ) ENGINE=NDB PARTITION BY KEY(account_id);
EOF
''')


@task
def prepare_mysql_cluster_for_benchmarking():
    execute(stop_mysql_cluster)
    execute(nuke_mysql_cluster)
    execute(configure_mysql_cluster)
    execute(start_mysql_cluster)
    execute(create_schema)


@task
@roles('data-nodes')
def install_iperf():
    execute(install_yum_repo_file)
    sudo('yum -y update')
    sudo('yum -y install iperf')
