#include <algorithm>
#include <cmath>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <random>
#include <sstream>
#include <string>
#include <unordered_map>
#include <vector>

struct Row {
    std::string symbol;
    std::string company;
    std::string timestamp;
    double open;
    double high;
    double low;
    double close;
    double volume;
};

struct Sample {
    std::vector<double> x;
    double y;
    double current_close;
};

struct MinMaxScaler {
    std::vector<double> min_vals;
    std::vector<double> max_vals;

    void fit(const std::vector<Sample>& samples) {
        if (samples.empty()) {
            return;
        }
        size_t d = samples[0].x.size();
        min_vals.assign(d, std::numeric_limits<double>::infinity());
        max_vals.assign(d, -std::numeric_limits<double>::infinity());

        for (const auto& s : samples) {
            for (size_t i = 0; i < d; ++i) {
                min_vals[i] = std::min(min_vals[i], s.x[i]);
                max_vals[i] = std::max(max_vals[i], s.x[i]);
            }
        }
    }

    std::vector<double> transform(const std::vector<double>& x) const {
        std::vector<double> out(x.size(), 0.0);
        for (size_t i = 0; i < x.size(); ++i) {
            double denom = max_vals[i] - min_vals[i];
            if (std::abs(denom) < 1e-12) {
                out[i] = 0.0;
            } else {
                out[i] = (x[i] - min_vals[i]) / denom;
            }
        }
        return out;
    }
};

struct TargetScaler {
    double y_min = 0.0;
    double y_max = 1.0;

    void fit(const std::vector<Sample>& samples) {
        y_min = std::numeric_limits<double>::infinity();
        y_max = -std::numeric_limits<double>::infinity();
        for (const auto& s : samples) {
            y_min = std::min(y_min, s.y);
            y_max = std::max(y_max, s.y);
        }
    }

    double transform(double y) const {
        double denom = y_max - y_min;
        if (std::abs(denom) < 1e-12) {
            return 0.0;
        }
        return (y - y_min) / denom;
    }

    double inverse(double ys) const {
        return ys * (y_max - y_min) + y_min;
    }
};

class SimpleNN {
public:
    SimpleNN(size_t input_dim, size_t hidden_dim, double lr)
        : in_dim(input_dim), hid_dim(hidden_dim), learning_rate(lr), rng(42) {
        init_params();
    }

    double forward(const std::vector<double>& x, std::vector<double>& z1, std::vector<double>& a1) const {
        z1.assign(hid_dim, 0.0);
        a1.assign(hid_dim, 0.0);

        for (size_t j = 0; j < hid_dim; ++j) {
            double sum = b1[j];
            for (size_t i = 0; i < in_dim; ++i) {
                sum += x[i] * W1[i][j];
            }
            z1[j] = sum;
            a1[j] = (sum > 0.0) ? sum : 0.0; // ReLU
        }

        double y_hat = b2;
        for (size_t j = 0; j < hid_dim; ++j) {
            y_hat += a1[j] * W2[j];
        }
        return y_hat;
    }

    void train(std::vector<Sample>& train_set, int epochs) {
        std::uniform_int_distribution<size_t> dist;

        for (int epoch = 1; epoch <= epochs; ++epoch) {
            std::shuffle(train_set.begin(), train_set.end(), rng);
            double epoch_loss = 0.0;

            for (const auto& s : train_set) {
                std::vector<double> z1, a1;
                double y_hat = forward(s.x, z1, a1);
                double diff = y_hat - s.y;
                epoch_loss += diff * diff;

                double dL_dy = 2.0 * diff;

                // Output layer gradients
                for (size_t j = 0; j < hid_dim; ++j) {
                    W2[j] -= learning_rate * dL_dy * a1[j];
                }
                b2 -= learning_rate * dL_dy;

                // Hidden layer gradients
                for (size_t j = 0; j < hid_dim; ++j) {
                    double dL_dz = dL_dy * W2[j] * ((z1[j] > 0.0) ? 1.0 : 0.0);
                    for (size_t i = 0; i < in_dim; ++i) {
                        W1[i][j] -= learning_rate * dL_dz * s.x[i];
                    }
                    b1[j] -= learning_rate * dL_dz;
                }
            }

            double mse = epoch_loss / static_cast<double>(train_set.size());
            if (epoch == 1 || epoch % 10 == 0 || epoch == epochs) {
                std::cout << "Epoch " << std::setw(3) << epoch << " | Train MSE: " << std::fixed << std::setprecision(6) << mse << "\n";
            }
        }
    }

    double predict(const std::vector<double>& x) const {
        std::vector<double> z1, a1;
        return forward(x, z1, a1);
    }

private:
    size_t in_dim;
    size_t hid_dim;
    double learning_rate;
    std::mt19937 rng;

    std::vector<std::vector<double>> W1;
    std::vector<double> b1;
    std::vector<double> W2;
    double b2 = 0.0;

    void init_params() {
        std::normal_distribution<double> nd(0.0, 0.05);

        W1.assign(in_dim, std::vector<double>(hid_dim, 0.0));
        b1.assign(hid_dim, 0.0);
        W2.assign(hid_dim, 0.0);

        for (size_t i = 0; i < in_dim; ++i) {
            for (size_t j = 0; j < hid_dim; ++j) {
                W1[i][j] = nd(rng);
            }
        }
        for (size_t j = 0; j < hid_dim; ++j) {
            W2[j] = nd(rng);
        }
        b2 = 0.0;
    }
};

static std::vector<std::string> split_csv_line(const std::string& line) {
    std::vector<std::string> fields;
    std::string cur;
    bool in_quotes = false;

    for (char c : line) {
        if (c == '"') {
            in_quotes = !in_quotes;
        } else if (c == ',' && !in_quotes) {
            fields.push_back(cur);
            cur.clear();
        } else {
            cur.push_back(c);
        }
    }
    fields.push_back(cur);
    return fields;
}

static std::string trim(const std::string& s) {
    size_t start = s.find_first_not_of(" \t\r\n");
    size_t end = s.find_last_not_of(" \t\r\n");
    if (start == std::string::npos) {
        return "";
    }
    return s.substr(start, end - start + 1);
}

static std::string to_lower(std::string s) {
    std::transform(s.begin(), s.end(), s.begin(), [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
    return s;
}

static int get_col_idx(const std::vector<std::string>& headers, const std::vector<std::string>& candidates) {
    std::unordered_map<std::string, int> idx;
    for (size_t i = 0; i < headers.size(); ++i) {
        idx[to_lower(trim(headers[i]))] = static_cast<int>(i);
    }
    for (const auto& name : candidates) {
        auto it = idx.find(to_lower(name));
        if (it != idx.end()) {
            return it->second;
        }
    }
    return -1;
}

static bool to_double_safe(const std::string& s, double& out) {
    try {
        std::string t = trim(s);
        if (t.empty()) {
            return false;
        }
        out = std::stod(t);
        return true;
    } catch (...) {
        return false;
    }
}

static std::vector<Row> load_csv(const std::string& path) {
    std::ifstream fin(path);
    if (!fin) {
        throw std::runtime_error("Failed to open CSV: " + path);
    }

    std::string line;
    if (!std::getline(fin, line)) {
        throw std::runtime_error("CSV is empty");
    }

    std::vector<std::string> headers = split_csv_line(line);

    int symbol_i = get_col_idx(headers, {"symbol", "ticker", "asset"});
    int company_i = get_col_idx(headers, {"company", "name"});
    int ts_i = get_col_idx(headers, {"timestamp", "date", "datetime", "time"});
    int open_i = get_col_idx(headers, {"open"});
    int high_i = get_col_idx(headers, {"high"});
    int low_i = get_col_idx(headers, {"low"});
    int close_i = get_col_idx(headers, {"close"});
    int vol_i = get_col_idx(headers, {"volume", "vol"});

    if (symbol_i < 0 || ts_i < 0 || open_i < 0 || high_i < 0 || low_i < 0 || close_i < 0 || vol_i < 0) {
        throw std::runtime_error(
            "CSV must contain columns: symbol,timestamp,open,high,low,close,volume (company optional)");
    }

    std::vector<Row> rows;
    while (std::getline(fin, line)) {
        if (trim(line).empty()) {
            continue;
        }
        auto fields = split_csv_line(line);
        if (static_cast<int>(fields.size()) <= std::max({symbol_i, ts_i, open_i, high_i, low_i, close_i, vol_i, company_i})) {
            continue;
        }

        double o = 0, h = 0, l = 0, c = 0, v = 0;
        if (!to_double_safe(fields[open_i], o) || !to_double_safe(fields[high_i], h) ||
            !to_double_safe(fields[low_i], l) || !to_double_safe(fields[close_i], c) || !to_double_safe(fields[vol_i], v)) {
            continue;
        }

        Row r;
        r.symbol = trim(fields[symbol_i]);
        r.company = (company_i >= 0) ? trim(fields[company_i]) : r.symbol;
        r.timestamp = trim(fields[ts_i]);
        r.open = o;
        r.high = h;
        r.low = l;
        r.close = c;
        r.volume = v;
        rows.push_back(r);
    }

    return rows;
}

static std::vector<Sample> build_samples(const std::vector<Row>& rows) {
    std::unordered_map<std::string, std::vector<Row>> by_symbol;
    std::unordered_map<std::string, std::string> symbol_to_company;

    for (const auto& r : rows) {
        by_symbol[r.symbol].push_back(r);
        symbol_to_company[r.symbol] = r.company;
    }

    std::vector<std::string> symbols;
    std::vector<std::string> companies;
    symbols.reserve(by_symbol.size());
    companies.reserve(by_symbol.size());

    for (const auto& kv : by_symbol) {
        symbols.push_back(kv.first);
        companies.push_back(symbol_to_company[kv.first]);
    }

    std::sort(symbols.begin(), symbols.end());
    std::sort(companies.begin(), companies.end());
    companies.erase(std::unique(companies.begin(), companies.end()), companies.end());

    std::unordered_map<std::string, int> symbol_idx;
    std::unordered_map<std::string, int> company_idx;
    for (size_t i = 0; i < symbols.size(); ++i) {
        symbol_idx[symbols[i]] = static_cast<int>(i);
    }
    for (size_t i = 0; i < companies.size(); ++i) {
        company_idx[companies[i]] = static_cast<int>(i);
    }

    size_t base_dim = 5; // O,H,L,C,V
    size_t onehot_sym = symbols.size();
    size_t onehot_company = companies.size();
    size_t input_dim = base_dim + onehot_sym + onehot_company;

    std::vector<Sample> samples;

    for (auto& kv : by_symbol) {
        auto& seq = kv.second;
        std::sort(seq.begin(), seq.end(), [](const Row& a, const Row& b) { return a.timestamp < b.timestamp; });

        int s_idx = symbol_idx[kv.first];
        int c_idx = company_idx[symbol_to_company[kv.first]];

        for (size_t t = 0; t + 1 < seq.size(); ++t) {
            std::vector<double> x(input_dim, 0.0);
            x[0] = seq[t].open;
            x[1] = seq[t].high;
            x[2] = seq[t].low;
            x[3] = seq[t].close;
            x[4] = seq[t].volume;

            x[base_dim + s_idx] = 1.0;
            x[base_dim + onehot_sym + c_idx] = 1.0;

            Sample s;
            s.x = std::move(x);
            s.y = seq[t + 1].close;
            s.current_close = seq[t].close;
            samples.push_back(std::move(s));
        }
    }

    return samples;
}

int main(int argc, char** argv) {
    if (argc < 2) {
        std::cerr << "Usage: " << argv[0] << " <data.csv> [epochs=100] [hidden=64] [lr=0.001]\n";
        std::cerr << "CSV required columns: symbol,timestamp,open,high,low,close,volume (company optional)\n";
        return 1;
    }

    std::string csv_path = argv[1];
    int epochs = (argc > 2) ? std::stoi(argv[2]) : 100;
    int hidden = (argc > 3) ? std::stoi(argv[3]) : 64;
    double lr = (argc > 4) ? std::stod(argv[4]) : 0.001;

    try {
        auto rows = load_csv(csv_path);
        if (rows.size() < 20) {
            throw std::runtime_error("Not enough rows after parsing.");
        }

        auto samples = build_samples(rows);
        if (samples.size() < 20) {
            throw std::runtime_error("Not enough supervised samples to train.");
        }

        std::mt19937 rng(42);
        std::shuffle(samples.begin(), samples.end(), rng);

        size_t split = static_cast<size_t>(samples.size() * 0.8);
        std::vector<Sample> train_set(samples.begin(), samples.begin() + split);
        std::vector<Sample> test_set(samples.begin() + split, samples.end());

        MinMaxScaler x_scaler;
        x_scaler.fit(train_set);

        TargetScaler y_scaler;
        y_scaler.fit(train_set);

        for (auto& s : train_set) {
            s.x = x_scaler.transform(s.x);
            s.y = y_scaler.transform(s.y);
        }
        for (auto& s : test_set) {
            s.x = x_scaler.transform(s.x);
            s.y = y_scaler.transform(s.y);
        }

        size_t input_dim = train_set[0].x.size();
        SimpleNN model(input_dim, static_cast<size_t>(hidden), lr);

        std::cout << "Loaded rows: " << rows.size() << "\n";
        std::cout << "Supervised samples: " << samples.size() << "\n";
        std::cout << "Train/Test: " << train_set.size() << "/" << test_set.size() << "\n";
        std::cout << "Input dim: " << input_dim << " | Hidden dim: " << hidden << "\n\n";

        model.train(train_set, epochs);

        // Evaluation
        double mae = 0.0;
        double mse = 0.0;
        int correct_dir = 0;

        for (const auto& s : test_set) {
            double y_pred_s = model.predict(s.x);
            double y_pred = y_scaler.inverse(y_pred_s);
            double y_true = y_scaler.inverse(s.y);

            double err = y_pred - y_true;
            mae += std::abs(err);
            mse += err * err;

            double actual_delta = y_true - s.current_close;
            double pred_delta = y_pred - s.current_close;
            if ((actual_delta >= 0.0 && pred_delta >= 0.0) || (actual_delta < 0.0 && pred_delta < 0.0)) {
                correct_dir++;
            }
        }

        mae /= static_cast<double>(test_set.size());
        mse /= static_cast<double>(test_set.size());
        double rmse = std::sqrt(mse);
        double direction_acc = 100.0 * static_cast<double>(correct_dir) / static_cast<double>(test_set.size());

        std::cout << "\nEvaluation Metrics\n";
        std::cout << "------------------\n";
        std::cout << "MAE: " << std::fixed << std::setprecision(4) << mae << "\n";
        std::cout << "RMSE: " << std::fixed << std::setprecision(4) << rmse << "\n";
        std::cout << "Direction Accuracy (%): " << std::fixed << std::setprecision(2) << direction_acc << "\n";

        return 0;
    } catch (const std::exception& ex) {
        std::cerr << "Error: " << ex.what() << "\n";
        return 1;
    }
}
