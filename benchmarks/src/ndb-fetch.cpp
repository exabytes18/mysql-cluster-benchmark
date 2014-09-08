#include <NdbApi.hpp>
#include <stdio.h>
#include <iostream>
#include <thread>

#define DATABASE_NAME "benchmarks"
#define TABLE_NAME "transactions"

#define PRINT_ERROR(code,msg) \
	std::cerr << "Error in " << __FILE__ << ", line: " << __LINE__ \
			  << ", code: " << code \
			  << ", msg: " << msg << "." << std::endl
#define APIERROR(error) { PRINT_ERROR(error.code, error.message); exit(-1); }


static int getRows(Ndb* ndb, const NdbDictionary::Index* index, int accountID) {
	int retryAttempt = 0;
	const int retryMax = 10;
	NdbRecAttr* myRecAttr[5];
	while (true) {
		if (retryAttempt >= retryMax) {
			std::cerr << "ERROR: has retried this operation " << retryAttempt << " times, failing!" << std::endl;
			return -1;
		}

		NdbTransaction* txn = ndb->startTransaction();
		if (txn == NULL) {
			const NdbError err = ndb->getNdbError();
			if (err.status == NdbError::TemporaryError) {
				retryAttempt++;
				continue;
			}
			std::cout << err.message << std::endl;
			return -1;
		}

		NdbIndexScanOperation* scan = txn->getNdbIndexScanOperation(index);
		if (scan == NULL) {
			std::cerr << txn->getNdbError().message << std::endl;
			txn->close();
			return -1;
		}

		if (scan->readTuples(NdbOperation::LM_CommittedRead) == -1) {
			std::cerr << txn->getNdbError().message << std::endl;
			txn->close();
			return -1;
		}

		// "WHERE" predicate
		scan->setBound("account_id", NdbIndexScanOperation::BoundEQ, &accountID);

		myRecAttr[0] = scan->getValue("account_id");
		myRecAttr[1] = scan->getValue("txn_id");
		myRecAttr[2] = scan->getValue("timestamp");
		myRecAttr[3] = scan->getValue("posted");
		myRecAttr[4] = scan->getValue("amount");
		if (myRecAttr[0] ==NULL || myRecAttr[1] == NULL || myRecAttr[2]==NULL || myRecAttr[3]==NULL || myRecAttr[4]==NULL) {
			std::cerr << txn->getNdbError().message << std::endl;
			txn->close();
			return -1;
		}

		if (txn->execute(NdbTransaction::NoCommit) != 0) {
			const NdbError err = txn->getNdbError();
			if (err.status == NdbError::TemporaryError) {
				std::cerr << txn->getNdbError().message << std::endl;
				txn->close();
				continue;
			}
			std::cerr << err.code << std::endl;
			std::cerr << err.message << std::endl;
			txn->close();
			return -1;
		}

		auto start = std::chrono::high_resolution_clock::now();
		int check;
		int numRows = 0;
		while ((check = scan->nextResult(true)) == 0) {
			do {
				int rowAccountID = myRecAttr[0]->int32_value();
				int rowTxnID = myRecAttr[1]->int32_value();
				int rowTimestamp = myRecAttr[2]->int32_value();
				int rowPosted = myRecAttr[3]->int8_value();
				float rowAmount = myRecAttr[4]->float_value();
				numRows++;
			} while ((check = scan->nextResult(false)) == 0);
		}
		txn->close();
		auto end = std::chrono::high_resolution_clock::now();

		long long microseconds = std::chrono::duration_cast<std::chrono::microseconds>(end-start).count();
		double millis = microseconds / 1000.;
		std::cout << "Fetch time: " << millis << "ms" << std::endl;

		return numRows;
	}
}


static void run(const char* connectionString, int accountID) {
	Ndb_cluster_connection cluster_connection(connectionString);
	if (cluster_connection.connect(4, 5, 1)) {
		std::cerr << "Unable to connect to cluster management server" << std::endl;
		exit(1);
	}
	if (cluster_connection.wait_until_ready(30, 0) < 0) {
		std::cerr << "Unable to connect to datanodes" << std::endl;
		exit(1);
	}

	Ndb ndb(&cluster_connection, DATABASE_NAME);
	if (ndb.init()) {
		APIERROR(ndb.getNdbError());
	}

	const NdbDictionary::Dictionary* dict = ndb.getDictionary();
	const NdbDictionary::Index* index = dict->getIndex("PRIMARY", TABLE_NAME);
	if (index == NULL) {
		APIERROR(dict->getNdbError());
	}

	const int n = 100;
	auto start = std::chrono::high_resolution_clock::now();
	for (int i = 0; i < n; i++) {
		getRows(&ndb, index, accountID);
	}
	auto end = std::chrono::high_resolution_clock::now();
	
	long long microseconds = std::chrono::duration_cast<std::chrono::microseconds>(end - start).count();
	double millis = microseconds / 1000.;
	std::cout << "Avg query time: " << (millis / n) << "ms" << std::endl;
}


int main(int argc, char** argv) {
	if (argc != 3) {
		std::cerr << "usage: " << argv[0] << "connectionString accountID" << std::endl;
		exit(1);
	}

	char* connectionString = argv[1];

	int accountID;
	try {
		accountID = std::stoi(argv[2]);
	} catch (std::invalid_argument e) {
		std::cerr << "Invalid accountID: '" << argv[2] << "'" << std::endl;
		exit(1);
	} catch (std::out_of_range e) {
		std::cerr << "Invalid accountID: '" << argv[2] << "'" << std::endl;
		exit(1);
	}
	if (accountID < 1) {
		std::cerr << "Invalid accountID: '" << argv[2] << "'; must be positive" << std::endl;
		exit(1);
	}

	ndb_init();
	run(connectionString, accountID);
	ndb_end(0);
	return 0;
}
