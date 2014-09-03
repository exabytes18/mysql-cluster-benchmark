import random
import string

from fabric.api import env
from fabric.context_managers import cd
from fabric.contrib.files import upload_template
from fabric.decorators import roles
from ec2 import *

env.ec2_key_pair_name = 'exabytes18@geneva'
env.ec2_vpc_id = 'vpc-eed33c8b'
env.ec2_region = 'us-west-1'
env.ec2_instances = {
    'datanodes': {
        'roles': ['datanode'],
        'type': 'r3.large',
        'ami': 'ami-f0d3d4b5',
        'count': 1,
        'bid': 0.02,
        'ephemeral_disks': ['/dev/sdb'],
        'assign_public_ip': False,
        'source_dest_check': True,
        'security_groups': ['mysql-cluster'],
        'placement_group': 'mysql-cluster',
        'subnet': 'subnet-cfd3ec89', # Private subnet (i.e., subnet with routing table containing default route to VPN instance)
    },

    'vpn': {
        'roles': ['vpn'],
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
    'vpn': get_instances_callable(
        role='vpn',
        mapper=lambda i: i.ip_address),
    'datanode': get_instances_callable(
        role='datanode',
        mapper=lambda i: i.private_ip_address),
}


@task
@roles('vpn')
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
        sudo('curl http://static.laazy.com/mirror/strongswan-5.2.0.tar.gz > strongswan-5.2.0.tar.gz')
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

    sudo('ipsec restart')
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
           '                0.0.0.0/0   -> "%s" (VPN and NAT combo)\n'
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
@roles('datanode')
def configure_datanodes():
    instance = get_instance_by_ip(env.host)
    if instance is None:
        abort('\n'
              '\n'
              '    Unable to find any datanode instances!')

    sudo('yum -y update')
